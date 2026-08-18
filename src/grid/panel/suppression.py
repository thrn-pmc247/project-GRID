"""Queue B - existing registered GP clinics not on the PMCare panel.

Queue B is the volume buffer that guarantees the 40-60 engagements/month KPI when new
openings run slow. It is derived **at read time** from `core.provider_outlet`; there is
no stored Queue B table, because a stored one would need invalidating and would become a
second place to get suppression wrong (ADR 0007).

Three rules govern the derivation:

* **Membership is decided by the point-in-time rule, never `status_code = 'A'`.**
  `TERMINATION_DATE` reaches 2028-08-05, so the two definitions already disagree on one
  row today and will disagree on more as future-dated terminations accumulate. The
  clause comes from `grid.pr001.staging.active_as_of_clause`, shared with staging so the
  two layers cannot drift.
* **Suppression is a filter, not a fuzzy match.** `pmcare_panel_status` is authoritative
  on the incumbent row (ADR 0005, restructure R2). There is nothing to match against.
* **Doubtful rows are routed, never dropped.** A row that looks like a duplicate of an
  on-panel clinic goes to a review segment where a human sees it. Silently discarding it
  would hide a data-quality problem; silently calling it would embarrass PNM.

Business data only. This module never imports or selects a personal-data column, which
is what allows its output to back a shareable view and the default workbook.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

import structlog
from sqlalchemy import Engine, and_, func, select, text
from sqlalchemy.sql.elements import ColumnElement

from grid.db.models import (
    CoreProviderCodeSupersession,
    CoreProviderOutlet,
    CoreRemarksSignal,
    StagingProviderOutlet,
)
from grid.normalise.addresses import postcode_prefix
from grid.pr001.staging import active_as_of_clause

log = structlog.get_logger(__name__)

GP_PROVIDER_TYPE_CODE: Final = "GP"
"""GRID is GP/primary care only (guardrail 7)."""

DEFAULT_WIN_BACK_SINCE: Final = dt.date(2024, 1, 1)
"""Terminations at least this recent are worth a win-back conversation."""

REVIEW_SIGNAL_TYPES: Final[frozenset[str]] = frozenset(
    {"closed", "known_duplicate", "duplicate_flag", "code_supersession"}
)
"""REMARKS signal types that mean "do not call this without looking first"."""


class Segment(StrEnum):
    """Which list a row belongs on."""

    NOT_ON_PANEL = "not_on_panel"
    """The call list."""

    WIN_BACK = "win_back"
    """Terminated recently — a different sales conversation, not a cold call."""

    REVIEW_LIKELY_ON_PANEL = "review_likely_on_panel"
    """Name and postcode collide with an on-panel outlet. Probably the same clinic."""

    REVIEW_FLAGGED = "review_flagged"
    """PNM's own notes say closed, duplicate or superseded."""


@dataclass(frozen=True, slots=True)
class QueueBRow:
    """One outlet on a Queue B list. Business data only — no phone, no doctor name."""

    provider_code: str
    name_raw: str | None
    name_normalised: str | None
    chain_base_name: str | None
    branch_qualifier: str | None
    address_unit: str | None
    address_street: str | None
    address_locality: str | None
    city_raw: str | None
    postcode_clean: str | None
    postcode_valid: bool
    postcode_prefix: str | None
    postcode_state_mismatch: bool | None
    state_code: str
    appointment_date: dt.datetime | None
    termination_date: dt.datetime | None
    segment: Segment
    chain_on_panel_outlets: int
    """How many outlets of the same inferred chain are already on panel. INFERRED —
    a shared base name can mean a real brand or the same premises keyed twice."""
    collides_with_provider_code: str | None
    review_flags: tuple[str, ...]
    panel_flag_conflict: bool
    """Terminated, yet still flagged on-panel. The two fields contradict each other."""


@dataclass(frozen=True, slots=True)
class SuppressionReport:
    """The funnel, counted at every step, so a reader can reconcile the number."""

    as_of: dt.date
    total_outlets: int
    gp_rows: int
    gp_active_as_of: int
    gp_active_status_code_a: int
    status_code_disagreements: int
    on_panel: int
    not_on_panel: int
    excluded_superseded: int
    routed_to_review_flagged: int
    routed_to_review_likely_on_panel: int
    win_back: int
    queue_b_final: int

    @property
    def reconciles(self) -> bool:
        """Whether the funnel adds up.

        Mirrors `PipelineReport.reconciles`: the counts either line up or the caller is
        told they do not.
        """
        return self.not_on_panel == (
            self.queue_b_final
            + self.excluded_superseded
            + self.routed_to_review_flagged
            + self.routed_to_review_likely_on_panel
        )


@dataclass(frozen=True, slots=True)
class QueueBPopulation:
    """Everything a Queue B export needs."""

    report: SuppressionReport
    call_list: tuple[QueueBRow, ...]
    win_back: tuple[QueueBRow, ...]
    review: tuple[QueueBRow, ...]


def _chain_foothold(engine: Engine, as_of: dt.date) -> dict[str, int]:
    """On-panel outlet count per inferred chain base name."""
    stmt = (
        select(CoreProviderOutlet.chain_base_name, func.count())
        .where(
            CoreProviderOutlet.chain_base_name.is_not(None),
            CoreProviderOutlet.pmcare_panel_status.is_(True),
            _active(as_of),
        )
        .group_by(CoreProviderOutlet.chain_base_name)
    )
    with engine.connect() as conn:
        return {str(name): int(count) for name, count in conn.execute(stmt)}


def _on_panel_blocking_keys(engine: Engine, as_of: dt.date) -> dict[tuple[str, str], str]:
    """Map (name_normalised, postcode_clean) → provider_code for active on-panel rows.

    This is the project's standard blocking key (ADR 0005). An exact collision on it
    between an off-panel and an on-panel row is near-certainly the same clinic keyed
    twice, not two clinics.
    """
    stmt = select(
        CoreProviderOutlet.name_normalised,
        CoreProviderOutlet.postcode_clean,
        CoreProviderOutlet.provider_code,
    ).where(
        CoreProviderOutlet.name_normalised.is_not(None),
        CoreProviderOutlet.postcode_clean.is_not(None),
        CoreProviderOutlet.pmcare_panel_status.is_(True),
        _active(as_of),
    )
    with engine.connect() as conn:
        return {(str(n), str(p)): str(code) for n, p, code in conn.execute(stmt)}


def _review_flags(engine: Engine) -> dict[str, tuple[str, ...]]:
    """Provider codes carrying a REMARKS signal that means "look before calling"."""
    stmt = (
        select(CoreRemarksSignal.provider_code, CoreRemarksSignal.signal_type)
        .where(CoreRemarksSignal.signal_type.in_(sorted(REVIEW_SIGNAL_TYPES)))
        .distinct()
    )
    flags: dict[str, set[str]] = {}
    with engine.connect() as conn:
        for code, signal_type in conn.execute(stmt):
            flags.setdefault(str(code), set()).add(str(signal_type))
    return {code: tuple(sorted(types)) for code, types in flags.items()}


def _superseded_codes(engine: Engine) -> set[str]:
    """Provider codes PNM's own notes say were replaced by another code."""
    with engine.connect() as conn:
        return {
            str(code)
            for (code,) in conn.execute(select(CoreProviderCodeSupersession.superseded_code))
        }


def _city_raw(engine: Engine) -> dict[str, str]:
    """`city_raw` per provider code, joined from staging.

    `core.provider_outlet` carries only `city_canonical`, which is deliberately NULL
    everywhere — 1,019 free-text city values are not a vocabulary we can canonicalise
    without a gazetteer. The raw town is still useful to a caller planning a route, so
    it is joined in here rather than added to core by migration.
    """
    stmt = select(StagingProviderOutlet.provider_code, StagingProviderOutlet.city_raw).where(
        StagingProviderOutlet.city_raw.is_not(None)
    )
    with engine.connect() as conn:
        return {str(code): str(city) for code, city in conn.execute(stmt)}


def _active(as_of: dt.date) -> ColumnElement[bool]:
    """The shared point-in-time clause, applied to `core.provider_outlet`."""
    return active_as_of_clause(
        CoreProviderOutlet.appointment_date,
        CoreProviderOutlet.termination_date,
        CoreProviderOutlet.suspension_date,
        as_of=as_of,
    )


def queue_b_population(
    engine: Engine,
    *,
    as_of: dt.date,
    provider_type_code: str = GP_PROVIDER_TYPE_CODE,
    win_back_since: dt.date | None = DEFAULT_WIN_BACK_SINCE,
    states: Sequence[str] | None = None,
) -> QueueBPopulation:
    """Derive Queue B and its adjacent segments.

    Args:
        engine: Engine with core built.
        as_of: The date activity is evaluated on. Never defaulted — a queue is always
            "as at" some date, and leaving it implicit is how historical runs go wrong.
        provider_type_code: Restricted to GP by default (guardrail 7).
        win_back_since: Terminations at least this recent form the win-back segment.
            None disables the segment.
        states: Optional state-code filter, for territory-by-territory working.

    Returns:
        The call list, the win-back list, the review list, and the funnel counts.
    """
    foothold = _chain_foothold(engine, as_of)
    on_panel_keys = _on_panel_blocking_keys(engine, as_of)
    flags = _review_flags(engine)
    superseded = _superseded_codes(engine)
    cities = _city_raw(engine)

    gp_only: ColumnElement[bool] = CoreProviderOutlet.provider_type_code == provider_type_code
    state_filter: ColumnElement[bool] | None = (
        CoreProviderOutlet.state_code.in_(list(states)) if states else None
    )

    def _scoped(*clauses: ColumnElement[bool]) -> list[ColumnElement[bool]]:
        out = [gp_only, *clauses]
        if state_filter is not None:
            out.append(state_filter)
        return out

    with engine.connect() as conn:
        outlet_table = CoreProviderOutlet.__table__
        total_outlets = int(
            conn.execute(select(func.count()).select_from(outlet_table)).scalar_one()
        )
        gp_rows = int(
            conn.execute(
                select(func.count()).select_from(CoreProviderOutlet.__table__).where(gp_only)
            ).scalar_one()
        )
        gp_active = int(
            conn.execute(
                select(func.count())
                .select_from(CoreProviderOutlet.__table__)
                .where(and_(gp_only, _active(as_of)))
            ).scalar_one()
        )
        gp_status_a = int(
            conn.execute(
                select(func.count())
                .select_from(CoreProviderOutlet.__table__)
                .where(and_(gp_only, CoreProviderOutlet.status_code == "A"))
            ).scalar_one()
        )
        disagreements = int(
            conn.execute(
                select(func.count())
                .select_from(CoreProviderOutlet.__table__)
                .where(
                    and_(
                        gp_only,
                        (CoreProviderOutlet.status_code == "A") != _active(as_of),
                    )
                )
            ).scalar_one()
        )

        outlet_stmt = (
            select(CoreProviderOutlet)
            .where(
                and_(*_scoped(_active(as_of), CoreProviderOutlet.pmcare_panel_status.is_(False)))
            )
            .order_by(CoreProviderOutlet.provider_code)
        )
        candidates: list[Mapping[str, Any]] = [
            dict(m) for m in conn.execute(outlet_stmt).mappings()
        ]

        on_panel_count = int(
            conn.execute(
                select(func.count())
                .select_from(CoreProviderOutlet.__table__)
                .where(
                    and_(*_scoped(_active(as_of), CoreProviderOutlet.pmcare_panel_status.is_(True)))
                )
            ).scalar_one()
        )

        win_back_rows: list[dict[str, object]] = []
        if win_back_since is not None:
            win_stmt = (
                select(CoreProviderOutlet)
                .where(
                    and_(
                        *_scoped(
                            CoreProviderOutlet.termination_date.is_not(None),
                            CoreProviderOutlet.termination_date
                            >= dt.datetime.combine(win_back_since, dt.time.min),
                            CoreProviderOutlet.termination_date
                            < dt.datetime.combine(as_of + dt.timedelta(days=1), dt.time.min),
                        )
                    )
                )
                .order_by(CoreProviderOutlet.termination_date.desc())
            )
            win_back_rows = [dict(m) for m in conn.execute(win_stmt).mappings()]

    call_list: list[QueueBRow] = []
    review: list[QueueBRow] = []
    excluded_superseded = 0

    for row in candidates:
        code = str(row["provider_code"])
        if code in superseded:
            excluded_superseded += 1
            continue

        row_flags = flags.get(code, ())
        key = (row["name_normalised"], row["postcode_clean"])
        collision = (
            on_panel_keys.get((str(key[0]), str(key[1])))
            if key[0] is not None and key[1] is not None
            else None
        )

        if row_flags:
            segment = Segment.REVIEW_FLAGGED
        elif collision is not None:
            segment = Segment.REVIEW_LIKELY_ON_PANEL
        else:
            segment = Segment.NOT_ON_PANEL

        built = _build_row(row, segment, foothold, cities, collision, row_flags)
        (review if segment is not Segment.NOT_ON_PANEL else call_list).append(built)

    win_back = tuple(
        _build_row(
            row,
            Segment.WIN_BACK,
            foothold,
            cities,
            None,
            flags.get(str(row["provider_code"]), ()),
        )
        for row in win_back_rows
    )

    report = SuppressionReport(
        as_of=as_of,
        total_outlets=total_outlets,
        gp_rows=gp_rows,
        gp_active_as_of=gp_active,
        gp_active_status_code_a=gp_status_a,
        status_code_disagreements=disagreements,
        on_panel=on_panel_count,
        not_on_panel=len(candidates),
        excluded_superseded=excluded_superseded,
        routed_to_review_flagged=sum(1 for r in review if r.segment is Segment.REVIEW_FLAGGED),
        routed_to_review_likely_on_panel=sum(
            1 for r in review if r.segment is Segment.REVIEW_LIKELY_ON_PANEL
        ),
        win_back=len(win_back),
        queue_b_final=len(call_list),
    )

    log.info(
        "queue_b.derived",
        as_of=as_of.isoformat(),
        call_list=len(call_list),
        win_back=len(win_back),
        review=len(review),
        reconciles=report.reconciles,
    )
    return QueueBPopulation(
        report=report,
        call_list=tuple(call_list),
        win_back=win_back,
        review=tuple(review),
    )


def _build_row(
    row: Mapping[str, Any],
    segment: Segment,
    foothold: dict[str, int],
    cities: dict[str, str],
    collision: str | None,
    review_flags: tuple[str, ...],
) -> QueueBRow:
    """Assemble one `QueueBRow` from a core outlet mapping."""
    m = row
    code = str(m["provider_code"])
    chain = m["chain_base_name"]
    postcode = m["postcode_clean"]
    terminated = m["termination_date"]

    return QueueBRow(
        provider_code=code,
        name_raw=m["name_raw"],
        name_normalised=m["name_normalised"],
        chain_base_name=chain,
        branch_qualifier=m["branch_qualifier"],
        address_unit=m["address_unit"],
        address_street=m["address_street"],
        address_locality=m["address_locality"],
        city_raw=cities.get(code),
        postcode_clean=postcode,
        postcode_valid=bool(m["postcode_valid"]),
        postcode_prefix=postcode_prefix(postcode),
        postcode_state_mismatch=m["postcode_state_mismatch"],
        state_code=str(m["state_code"]),
        appointment_date=m["appointment_date"],
        termination_date=terminated,
        segment=segment,
        chain_on_panel_outlets=foothold.get(str(chain), 0) if chain else 0,
        collides_with_provider_code=collision,
        review_flags=review_flags,
        panel_flag_conflict=bool(terminated is not None and m["pmcare_panel_status"]),
    )


def suppression_report(engine: Engine, *, as_of: dt.date) -> SuppressionReport:
    """The funnel counts alone, without materialising the lists."""
    return queue_b_population(engine, as_of=as_of).report


QUEUE_B_VIEW_NAME: Final = "v_queue_b"


def create_queue_b_view(engine: Engine, *, as_of: dt.date) -> None:
    """Create `core.v_queue_b` — the call list as a shareable view.

    Deliberately **core-only**: it omits `city_raw`, which lives in staging. SQLite
    cannot define a view in one attached database that references another, and under
    ADR 0006 the same DDL has to run on both engines. The Python path in
    `queue_b_population` does the staging join instead, so the view is a shareable
    projection rather than the export's data source.

    Registering it in `grid.pr001.pdpa.SHAREABLE_VIEWS` means the existing PDPA audit
    covers Queue B automatically — a restricted column appearing here fails the build
    with no new test.
    """
    next_midnight = dt.datetime.combine(as_of + dt.timedelta(days=1), dt.time.min)
    boundary = next_midnight.isoformat(sep=" ")
    sql = f"""
    CREATE VIEW core.{QUEUE_B_VIEW_NAME} AS
    SELECT
        o.provider_code,
        o.name_normalised,
        o.chain_base_name,
        o.branch_qualifier,
        o.address_locality,
        o.postcode_clean,
        o.postcode_valid,
        o.postcode_state_mismatch,
        o.state_code,
        o.appointment_date,
        o.coord_quality
    FROM core.provider_outlet AS o
    WHERE o.provider_type_code = '{GP_PROVIDER_TYPE_CODE}'
      AND o.pmcare_panel_status = 0
      AND (o.appointment_date IS NULL OR o.appointment_date < '{boundary}')
      AND (o.termination_date IS NULL OR o.termination_date >= '{boundary}')
      AND (o.suspension_date IS NULL OR o.suspension_date >= '{boundary}')
      AND o.provider_code NOT IN (
            SELECT s.superseded_code FROM core.provider_code_supersession AS s
      )
    """
    postgres_sql = sql.replace("o.pmcare_panel_status = 0", "o.pmcare_panel_status IS FALSE")
    with engine.begin() as conn:
        conn.execute(text(f"DROP VIEW IF EXISTS core.{QUEUE_B_VIEW_NAME}"))
        conn.execute(text(sql if engine.dialect.name == "sqlite" else postgres_sql))
