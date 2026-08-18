"""Staging transforms — typed, cleaned, one row per bronze row of the current generation.

Everything here is reversible from bronze and accounted for in `ops.transform_log`. The
governing rule is the project's: where the data does not tell us something, the model
records that it does not know. Nothing is coerced into looking clean.

Transforms applied, in order:

1. **Unknown-code guard** — every classification code must be declared (`reference.py`).
2. **Reference derivation** — `ref_user` (case-folded staff identities), `ref_city`
   (keyed on city + postcode prefix) and the empirical postcode-prefix/state mapping.
3. **Timestamps** — micros-since-epoch decoded by the bronze load; the
   `ACC_VENDOR_FLAG_DATE = 1900-01-01` sentinel is remapped to NULL and counted.
4. **Times** — nanos-since-midnight decoded; where all four hour columns read 00:00:00
   the row is treated as unset and `operating_hours_present` is false.
5. **Coordinates** — `grid.normalise.coordinates`, six-valued quality enum.
6. **Names** — `grid.normalise.names`, chain base name and branch qualifier.
7. **Addresses** — `grid.normalise.addresses`, best-effort parse with raw lines retained.

A transform that changes a larger share of rows than its configured threshold raises
rather than proceeds: silent mass mutation is the failure this accounting exists to
catch.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import structlog
from sqlalchemy import Engine, Row, and_, delete, func, insert, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session
from sqlalchemy.sql.elements import ColumnElement

from grid.db.models import (
    OpsLoadLog,
    OpsTransformLog,
    RefCity,
    RefPostcodePrefixState,
    RefUser,
    StagingProviderOutlet,
    pr001_provider_master,
)
from grid.normalise.addresses import normalise_postcode, parse_address_lines, postcode_prefix
from grid.normalise.coordinates import CoordQuality, assess_coordinates
from grid.normalise.names import parse_provider_name
from grid.pr001.columns import ACC_VENDOR_FLAG_SENTINEL_YEAR, USER_ID_COLUMNS
from grid.pr001.reference import assert_codes_known

log = structlog.get_logger(__name__)

DEFAULT_THRESHOLDS: Final[Mapping[str, float]] = {
    # Share of rows a transform may change before it is treated as a runaway.
    "acc_vendor_sentinel_to_null": 0.60,  # observed 0.38 (12,877 of 33,643)
    "operating_hours_unset": 1.00,  # observed 0.975 — the column is 2.5% filled
    "coordinate_gate": 1.00,  # classification touches every row by design
    "coordinate_repair": 0.01,  # a repair rate above 1% means the rule is too loose
    # Case-folding legitimately rewrites nearly every staff ID (the source stores them
    # upper-case), so a share threshold carries no signal here. The meaningful number is
    # `case_collisions` — identities that appeared under more than one spelling — which
    # is reported separately in StagingResult.
    "user_case_fold": 1.00,
    "postcode_invalid": 0.20,
    "name_parse": 1.00,
}

_MODAL_SHARE_FLOOR: Final = 0.80
"""A postcode prefix must map to one state this consistently before a disagreement is
reported as a mismatch. Below it the empirical mapping is too noisy to accuse either
field of being wrong."""

_MIN_PREFIX_OBSERVATIONS: Final = 20


class TransformThresholdError(RuntimeError):
    """A transform changed more rows than its threshold allows."""


@dataclass(slots=True)
class TransformCounter:
    """Accumulates per-transform counts for `ops.transform_log`."""

    load_id: str
    rows_total: int
    thresholds: Mapping[str, float] = field(default_factory=lambda: DEFAULT_THRESHOLDS)
    considered: Counter[str] = field(default_factory=Counter)
    changed: Counter[str] = field(default_factory=Counter)
    detail: dict[str, str] = field(default_factory=dict)

    def record(self, name: str, *, changed: bool, considered: bool = True) -> None:
        """Count one row against a named transform."""
        if considered:
            self.considered[name] += 1
        if changed:
            self.changed[name] += 1

    def share(self, name: str) -> float:
        """Changed as a share of what the transform actually considered.

        The denominator is `considered`, not the row count: a transform may inspect
        several values per row (the four staff user-ID columns are one transform over
        four columns), so dividing by rows would report well over 100%.
        """
        considered = self.considered[name] or self.rows_total
        return self.changed[name] / considered if considered else 0.0

    def check_thresholds(self) -> None:
        """Raise if any transform changed more of what it saw than its threshold allows."""
        breaches: list[str] = []
        for name in self.changed:
            threshold = self.thresholds.get(name)
            if threshold is None:
                continue
            share = self.share(name)
            if share > threshold:
                breaches.append(
                    f"{name}: changed {self.changed[name]:,} of "
                    f"{self.considered[name] or self.rows_total:,} values considered "
                    f"({share:.1%}) against a threshold of {threshold:.0%}"
                )
        if breaches:
            raise TransformThresholdError(
                "Transforms changed more rows than allowed:\n  "
                + "\n  ".join(breaches)
                + "\n\nEither the source has changed materially or the transform is "
                "wrong. Investigate before raising the threshold."
            )

    def rows(self) -> list[dict[str, object]]:
        """Serialise to `ops.transform_log` rows."""
        out: list[dict[str, object]] = []
        for name in sorted(set(self.considered) | set(self.changed)):
            threshold = self.thresholds.get(name)
            changed = self.changed[name]
            share = changed / self.rows_total if self.rows_total else 0.0
            out.append(
                {
                    "transform_log_id": str(
                        uuid.uuid5(uuid.NAMESPACE_OID, f"{self.load_id}:{name}")
                    ),
                    "load_id": self.load_id,
                    "transform_name": name,
                    "rows_considered": self.considered[name],
                    "rows_changed": changed,
                    "threshold": threshold,
                    "breached": bool(threshold is not None and share > threshold),
                    "detail": self.detail.get(name),
                }
            )
        return out


# --------------------------------------------------------------------------------------
# Reference derivation
# --------------------------------------------------------------------------------------


def _clean(value: object) -> str | None:
    """Trim a source string, treating blank as absent.

    PR001 uses NULL and blank interchangeably — `WEBSITE` alone has 13,708 of one and
    19,852 of the other — so every read goes through here.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def derive_ref_user(engine: Engine, ingest_id: str) -> dict[str, int]:
    """Build canonical staff identities from the four user-ID columns.

    The same person appears as `M_NOOR` and `m_noor`. The canonical key is the
    lowercased form; every raw variant observed is retained so an audit can trace a row
    back to the spelling the source used.
    """
    variants: defaultdict[str, set[str]] = defaultdict(set)
    columns: defaultdict[str, set[str]] = defaultdict(set)

    stmt = select(*(pr001_provider_master.c[c] for c in USER_ID_COLUMNS)).where(
        pr001_provider_master.c._ingest_id == ingest_id
    )
    with engine.connect() as conn:
        for row in conn.execute(stmt):
            for column, value in zip(USER_ID_COLUMNS, row, strict=True):
                raw = _clean(value)
                if raw is None:
                    continue
                canonical = raw.lower()
                variants[canonical].add(raw)
                columns[canonical].add(column)

    with Session(engine) as session:
        session.execute(delete(RefUser))
        for canonical in sorted(variants):
            session.add(
                RefUser(
                    user_id=canonical,
                    raw_variants="|".join(sorted(variants[canonical])),
                    seen_in_columns="|".join(sorted(columns[canonical])),
                    first_seen_ingest_id=ingest_id,
                )
            )
        session.commit()

    collisions = sum(1 for c in variants if len(variants[c]) > 1)
    log.info("staging.ref_user", users=len(variants), case_collisions=collisions)
    return {"users": len(variants), "case_collisions": collisions}


def derive_postcode_prefix_state(engine: Engine, ingest_id: str) -> int:
    """Derive the empirical postcode-prefix to state mapping from the extract itself.

    Open question 12 forbids coding this table "from folklore ranges" and the
    authoritative Pos Malaysia dataset is unresolved, so the mapping is *observed*, not
    asserted: for each two-digit prefix, the modal state and how dominant it is. It
    supports a mismatch flag only — never an overwrite of either field.
    """
    stmt = select(pr001_provider_master.c.POSTCODE, pr001_provider_master.c.STATE_CODE).where(
        pr001_provider_master.c._ingest_id == ingest_id
    )

    tally: defaultdict[str, Counter[str]] = defaultdict(Counter)
    with engine.connect() as conn:
        for postcode, state in conn.execute(stmt):
            clean, valid = normalise_postcode(postcode)
            prefix = postcode_prefix(clean) if valid else None
            state_code = _clean(state)
            if prefix and state_code:
                tally[prefix][state_code] += 1

    with Session(engine) as session:
        session.execute(delete(RefPostcodePrefixState))
        written = 0
        for prefix in sorted(tally):
            counts = tally[prefix]
            total = sum(counts.values())
            if total < _MIN_PREFIX_OBSERVATIONS:
                continue
            modal_state, modal_count = counts.most_common(1)[0]
            session.add(
                RefPostcodePrefixState(
                    postcode_prefix=prefix,
                    modal_state_code=modal_state,
                    modal_share=modal_count / total,
                    observation_count=total,
                    source="inferred",
                )
            )
            written += 1
        session.commit()

    log.info("staging.ref_postcode_prefix_state", prefixes=written)
    return written


def derive_ref_city(engine: Engine, ingest_id: str) -> int:
    """Seed `ref_city` from the data, keyed on (city_raw, postcode_prefix).

    `city_canonical` is left NULL for every seeded row — canonicalisation needs a human
    or an authoritative gazetteer, and 1,019 free-text values are not a vocabulary we
    can invent one from. Rows are flagged, never guessed.
    """
    stmt = select(pr001_provider_master.c.CITY, pr001_provider_master.c.POSTCODE).where(
        pr001_provider_master.c._ingest_id == ingest_id
    )

    tally: Counter[tuple[str, str]] = Counter()
    with engine.connect() as conn:
        for city, postcode in conn.execute(stmt):
            city_raw = _clean(city)
            clean, valid = normalise_postcode(postcode)
            prefix = postcode_prefix(clean) if valid else None
            if city_raw and prefix:
                tally[(city_raw.upper(), prefix)] += 1

    with Session(engine) as session:
        session.execute(delete(RefCity))
        for (city_raw, prefix), count in sorted(tally.items()):
            session.add(
                RefCity(
                    city_raw=city_raw,
                    postcode_prefix=prefix,
                    city_canonical=None,
                    source="unknown",
                    row_count=count,
                    notes="Seeded from PR001. Canonical form unresolved — flagged, not guessed.",
                )
            )
        session.commit()

    log.info("staging.ref_city", entries=len(tally))
    return len(tally)


# --------------------------------------------------------------------------------------
# The main transform
# --------------------------------------------------------------------------------------

_SELECT_COLUMNS: Final[tuple[str, ...]] = (
    "PROVIDER_CODE",
    "ROW_GUID",
    "MIX_ROW_ID",
    "PROVIDER_DESCRIPTION",
    "PROVIDER_TYPE_CODE",
    "CATEGORY_CODE",
    "PAYMENT_METHOD_CODE",
    "STATUS_CODE",
    "STATE_CODE",
    "OWNERSHIP_CODE",
    "id_LK180",
    "PMCARE_PANEL_STATUS",
    "ADDRESS1",
    "ADDRESS2",
    "ADDRESS3",
    "CITY",
    "POSTCODE",
    "LATITUDE",
    "LONGITUDE",
    "APPOINMENT_DATE",
    "TERMINATION_DATE",
    "SUSPENSION_DATE",
    "STATUS_DATE",
    "CREATE_DATE",
    "MODIFY_DATE",
    "SYS_TIME_STAMP",
    "ACC_VENDOR_FLAG_DATE",
    "STANDARD_HOUR_FROM",
    "STANDARD_HOUR_TO",
    "PUBLIC_HOUR_FROM",
    "PUBLIC_HOUR_TO",
    "STATUS_BY",
    "CREATE_BY",
    "MODIFY_BY",
    "GL_ELIGIBILITY_APPROVE_BY",
    "MEDILINE_USER",
    "OPEN24HOURS",
    "OPEN_PUBLIC_HOLIDAYS",
    "GL_ELIGIBILITY_STATUS",
    "ACC_VENDOR_FLAG",
    "isPMRused",
    "isAME",
    "IsAME_MPM",
    "isLTM",
    "IsEfarma",
    "isPERKESO",
    "isOH",
    "NO_DOCTOR_MALE",
    "NO_DOCTOR_FEMALE",
    "GENERAL_FAX_NO",
    "GST_REG_NO",
    "GST_COMPANY_NAME",
    "REMARKS",
    "SYS_ADMIN_REMARKS",
    "WEBSITE",
    "_row_ordinal",
)


@dataclass(frozen=True, slots=True)
class StagingResult:
    """Outcome of one staging transform."""

    load_id: str
    ingest_id: str
    rows_in: int
    rows_out: int
    coord_quality_counts: Mapping[str, int]
    acc_vendor_sentinel_remapped: int
    operating_hours_present: int
    postcode_invalid: int
    postcode_state_mismatch: int
    city_unmatched: int
    user_case_collisions: int


def transform_staging(
    engine: Engine,
    ingest_id: str,
    *,
    started_at: dt.datetime | None = None,
    thresholds: Mapping[str, float] | None = None,
) -> StagingResult:
    """Build `staging.provider_outlet` from one bronze generation.

    Raises:
        UnknownCodeError: a classification code is not declared in its reference table.
        TransformThresholdError: a transform changed more rows than its threshold allows.
    """
    stamp = started_at or dt.datetime.now(dt.UTC).replace(tzinfo=None)
    load_id = str(uuid.uuid5(uuid.NAMESPACE_OID, f"staging:{ingest_id}"))

    assert_codes_known(engine, ingest_id)
    user_stats = derive_ref_user(engine, ingest_id)
    derive_postcode_prefix_state(engine, ingest_id)
    derive_ref_city(engine, ingest_id)

    prefix_map = _load_prefix_map(engine)

    with engine.connect() as conn:
        rows_in = int(
            conn.execute(
                select(func.count())
                .select_from(pr001_provider_master)
                .where(pr001_provider_master.c._ingest_id == ingest_id)
            ).scalar_one()
        )

    counter = TransformCounter(
        load_id=load_id, rows_total=rows_in, thresholds=thresholds or DEFAULT_THRESHOLDS
    )
    coord_counts: Counter[str] = Counter({q.value: 0 for q in CoordQuality})
    tallies: Counter[str] = Counter()

    records: list[dict[str, object]] = []
    for row in _iter_bronze(engine, ingest_id):
        records.append(_build_row(row, ingest_id, prefix_map, counter, coord_counts, tallies))

    counter.check_thresholds()

    with Session(engine) as session:
        session.execute(delete(StagingProviderOutlet))
        # Replace-on-rebuild, deliberately, so the pipeline is re-runnable over one
        # extract. `load_id` is derived from `ingest_id`, so re-running staging on the
        # same generation would otherwise collide on the ops.load_log primary key and
        # raise IntegrityError — which would block the monthly refresh runbook and any
        # retry after a partial failure.
        #
        # Replace (rather than an append-only log with a random load_id) is the right
        # half of that trade because it matches what staging itself does: the layer is
        # deleted and rebuilt, so its accounting describes the *current* contents, not a
        # history of attempts. The append-only audit trail of what actually arrived lives
        # in bronze.pr001_generation, which is never rewritten.
        #
        # Transform rows go first — ops.transform_log has an FK onto ops.load_log.
        session.execute(delete(OpsTransformLog).where(OpsTransformLog.load_id == load_id))
        session.execute(delete(OpsLoadLog).where(OpsLoadLog.load_id == load_id))
        session.commit()

    with engine.begin() as conn:
        for start in range(0, len(records), 2_000):
            conn.execute(insert(StagingProviderOutlet), records[start : start + 2_000])
        conn.execute(
            insert(OpsLoadLog),
            {
                "load_id": load_id,
                "ingest_id": ingest_id,
                "layer": "staging",
                "source_filename": "bronze.pr001_provider_master",
                "source_sha256": "",
                "rows_in": rows_in,
                "rows_out": len(records),
                "outcome": "ok",
                "detail": None,
                "started_at": stamp,
                "finished_at": stamp,
            },
        )
        conn.execute(insert(OpsTransformLog), counter.rows())

    result = StagingResult(
        load_id=load_id,
        ingest_id=ingest_id,
        rows_in=rows_in,
        rows_out=len(records),
        coord_quality_counts=dict(sorted(coord_counts.items())),
        acc_vendor_sentinel_remapped=counter.changed["acc_vendor_sentinel_to_null"],
        operating_hours_present=tallies["operating_hours_present"],
        postcode_invalid=counter.changed["postcode_invalid"],
        postcode_state_mismatch=tallies["postcode_state_mismatch"],
        city_unmatched=tallies["city_unmatched"],
        user_case_collisions=user_stats["case_collisions"],
    )
    log.info("staging.complete", rows_out=result.rows_out, **result.coord_quality_counts)
    return result


def _iter_bronze(engine: Engine, ingest_id: str) -> Iterator[Row[Any]]:
    """Stream one bronze generation in source order."""
    stmt = (
        select(*(pr001_provider_master.c[c] for c in _SELECT_COLUMNS))
        .where(pr001_provider_master.c._ingest_id == ingest_id)
        .order_by(pr001_provider_master.c._row_ordinal)
    )
    with engine.connect() as conn:
        yield from conn.execute(stmt).yield_per(2_000)


def _load_prefix_map(engine: Engine) -> Mapping[str, tuple[str, float]]:
    """Postcode prefix to (modal state, modal share)."""
    with Session(engine) as session:
        return {
            r.postcode_prefix: (r.modal_state_code, r.modal_share)
            for r in session.execute(select(RefPostcodePrefixState)).scalars()
        }


def _remap_sentinel(value: dt.datetime | None) -> tuple[dt.datetime | None, bool]:
    """Map the 1900-01-01 'not set' sentinel to NULL. Returns (value, was_remapped)."""
    if value is not None and value.year == ACC_VENDOR_FLAG_SENTINEL_YEAR:
        return None, True
    return value, False


def _hours(
    values: Sequence[dt.time | None],
) -> tuple[tuple[dt.time | None, ...], bool]:
    """Decide whether a row's operating hours carry any signal.

    The four hour columns are populated for only 836 rows, and use 00:00:00 as a
    placeholder within those. All-midnight means unset, not "opens at midnight".
    """
    present = [v for v in values if v is not None]
    if not present or all(v == dt.time(0, 0) for v in present):
        return (None, None, None, None), False
    return tuple(values), True


def _build_row(
    row: Row[Any],
    ingest_id: str,
    prefix_map: Mapping[str, tuple[str, float]],
    counter: TransformCounter,
    coord_counts: Counter[str],
    tallies: Counter[str],
) -> dict[str, object]:
    """Transform one bronze row into a staging row."""
    data = row._mapping

    name = parse_provider_name(_clean(data["PROVIDER_DESCRIPTION"]))
    counter.record("name_parse", changed=bool(name.branch_qualifier))

    address = parse_address_lines(
        _clean(data["ADDRESS1"]), _clean(data["ADDRESS2"]), _clean(data["ADDRESS3"])
    )

    postcode_raw = _clean(data["POSTCODE"])
    postcode_clean, postcode_valid = normalise_postcode(postcode_raw)
    counter.record("postcode_invalid", changed=bool(postcode_raw and not postcode_valid))

    state_code = str(data["STATE_CODE"]).strip()
    mismatch: bool | None = None
    prefix = postcode_prefix(postcode_clean) if postcode_valid else None
    if prefix is not None:
        entry = prefix_map.get(prefix)
        if entry is not None and entry[1] >= _MODAL_SHARE_FLOOR:
            mismatch = entry[0] != state_code
            if mismatch:
                tallies["postcode_state_mismatch"] += 1

    coord = assess_coordinates(data["LATITUDE"], data["LONGITUDE"])
    coord_counts[coord.quality.value] += 1
    counter.record("coordinate_gate", changed=coord.quality is not CoordQuality.VALID)
    counter.record(
        "coordinate_repair",
        changed=coord.quality in (CoordQuality.REPAIRED_DECIMAL, CoordQuality.REPAIRED_SPLIT),
    )

    acc_vendor, remapped = _remap_sentinel(data["ACC_VENDOR_FLAG_DATE"])
    counter.record("acc_vendor_sentinel_to_null", changed=remapped)

    hours, hours_present = _hours(
        [
            data["STANDARD_HOUR_FROM"],
            data["STANDARD_HOUR_TO"],
            data["PUBLIC_HOUR_FROM"],
            data["PUBLIC_HOUR_TO"],
        ]
    )
    counter.record("operating_hours_unset", changed=not hours_present)
    if hours_present:
        tallies["operating_hours_present"] += 1

    city_raw = _clean(data["CITY"])
    city_unmatched = city_raw is not None
    if city_unmatched:
        tallies["city_unmatched"] += 1

    def user(column: str) -> str | None:
        raw = _clean(data[column])
        if raw is None:
            return None
        counter.record("user_case_fold", changed=raw != raw.lower())
        return raw.lower()

    lk180 = data["id_LK180"]

    return {
        "provider_code": str(data["PROVIDER_CODE"]).strip(),
        "row_guid": str(data["ROW_GUID"]).strip(),
        "ingest_id": ingest_id,
        "row_ordinal": data["_row_ordinal"],
        "mix_row_id": data["MIX_ROW_ID"],
        "provider_type_code": str(data["PROVIDER_TYPE_CODE"]).strip(),
        "category_code": str(data["CATEGORY_CODE"]).strip(),
        "payment_method_code": str(data["PAYMENT_METHOD_CODE"]).strip(),
        "status_code": str(data["STATUS_CODE"]).strip(),
        "state_code": state_code,
        "ownership_code": _clean(data["OWNERSHIP_CODE"]),
        "lk180_code": None if lk180 is None else str(lk180),
        "name_raw": name.name_raw or None,
        "name_normalised": name.name_normalised or None,
        "chain_base_name": name.chain_base_name or None,
        "branch_qualifier": name.branch_qualifier,
        "branch_qualifier_expanded": name.branch_qualifier_expanded,
        "address1_raw": _clean(data["ADDRESS1"]),
        "address2_raw": _clean(data["ADDRESS2"]),
        "address3_raw": _clean(data["ADDRESS3"]),
        "address_unit": address.address_unit,
        "address_street": address.address_street,
        "address_locality": address.address_locality,
        "city_raw": city_raw,
        "city_canonical": None,
        "city_unmatched": city_unmatched,
        "postcode_raw": postcode_raw,
        "postcode_clean": postcode_clean,
        "postcode_valid": postcode_valid,
        "postcode_state_mismatch": mismatch,
        "latitude_raw": data["LATITUDE"],
        "longitude_raw": data["LONGITUDE"],
        "latitude_clean": coord.latitude_clean,
        "longitude_clean": coord.longitude_clean,
        "coord_quality": coord.quality.value,
        "coord_repair_note": coord.repair_note,
        "pmcare_panel_status": bool(data["PMCARE_PANEL_STATUS"]),
        "appointment_date": data["APPOINMENT_DATE"],
        "termination_date": data["TERMINATION_DATE"],
        "suspension_date": data["SUSPENSION_DATE"],
        "status_date": data["STATUS_DATE"],
        "create_date": data["CREATE_DATE"],
        "modify_date": data["MODIFY_DATE"],
        "sys_time_stamp": data["SYS_TIME_STAMP"],
        "acc_vendor_flag_date": acc_vendor,
        "standard_hour_from": hours[0],
        "standard_hour_to": hours[1],
        "public_hour_from": hours[2],
        "public_hour_to": hours[3],
        "operating_hours_present": hours_present,
        "status_by": user("STATUS_BY"),
        "create_by": user("CREATE_BY"),
        "modify_by": user("MODIFY_BY"),
        "gl_eligibility_approve_by": user("GL_ELIGIBILITY_APPROVE_BY"),
        "mediline_user": data["MEDILINE_USER"],
        "open_24_hours": data["OPEN24HOURS"],
        "open_public_holidays": data["OPEN_PUBLIC_HOLIDAYS"],
        "gl_eligibility_status": data["GL_ELIGIBILITY_STATUS"],
        "acc_vendor_flag": data["ACC_VENDOR_FLAG"],
        "is_pmr_used": data["isPMRused"],
        "is_ame": data["isAME"],
        "is_ame_mpm": data["IsAME_MPM"],
        "is_ltm": data["isLTM"],
        "is_efarma": data["IsEfarma"],
        "is_perkeso": data["isPERKESO"],
        "is_oh": data["isOH"],
        "no_doctor_male": data["NO_DOCTOR_MALE"],
        "no_doctor_female": data["NO_DOCTOR_FEMALE"],
        "general_fax_no": _clean(data["GENERAL_FAX_NO"]),
        "gst_reg_no": _clean(data["GST_REG_NO"]),
        "gst_company_name": _clean(data["GST_COMPANY_NAME"]),
        "remarks": _clean(data["REMARKS"]),
        "sys_admin_remarks": _clean(data["SYS_ADMIN_REMARKS"]),
        "website": _clean(data["WEBSITE"]),
    }


# --------------------------------------------------------------------------------------
# Point-in-time status
# --------------------------------------------------------------------------------------


DateColumn = ColumnElement["dt.datetime | None"] | InstrumentedAttribute["dt.datetime | None"]
"""Either a Core column or a mapped ORM attribute holding a nullable timestamp.

Both are accepted so `active_as_of_clause` can be applied to `staging.provider_outlet`
and `core.provider_outlet` alike without a cast at either call site.
"""


def active_as_of_clause(
    appointment: DateColumn,
    termination: DateColumn,
    suspension: DateColumn,
    *,
    as_of: dt.date,
) -> ColumnElement[bool]:
    """Set-based form of the point-in-time activity rule.

    Takes columns rather than a model so `staging.provider_outlet` and
    `core.provider_outlet` share one definition of "active" instead of each growing its
    own. `is_active_as_of` is built on this, so the row-wise and set-based answers cannot
    drift apart — an equivalence test pins that.

    Deliberately **not** `termination_date IS NULL`. See `is_active_as_of`.

    Args:
        appointment: The appointment-date column.
        termination: The termination-date column.
        suspension: The suspension-date column.
        as_of: The date to evaluate activity on.

    Returns:
        A boolean SQL expression suitable for a `WHERE` clause.
    """
    # One boundary for all three comparisons: everything strictly before midnight at the
    # end of `as_of` has happened, everything at or after it has not. Using a single
    # instant avoids date/datetime coercion differences between SQLite and Postgres.
    next_midnight = dt.datetime.combine(as_of + dt.timedelta(days=1), dt.time.min)
    return and_(
        or_(appointment.is_(None), appointment < next_midnight),
        or_(termination.is_(None), termination >= next_midnight),
        or_(suspension.is_(None), suspension >= next_midnight),
    )


def is_active_as_of(engine: Engine, provider_code: str, as_of_date: dt.date) -> bool:
    """Whether a provider was active on a given date.

    Deliberately not `termination_date IS NULL`. `TERMINATION_DATE` reaches 2028-08-05,
    so a row can be flagged terminated today while still having been active for the
    period being reported on. Testing for a non-null date would silently return the
    wrong answer for any historical month, and would get worse as future-dated
    terminations accumulate.

    A provider is active as of `as_of_date` when it had been appointed by then, and
    neither its termination nor its suspension had yet taken effect.
    """
    stmt = select(StagingProviderOutlet.provider_code).where(
        StagingProviderOutlet.provider_code == provider_code,
        active_as_of_clause(
            StagingProviderOutlet.appointment_date,
            StagingProviderOutlet.termination_date,
            StagingProviderOutlet.suspension_date,
            as_of=as_of_date,
        ),
    )
    with engine.connect() as conn:
        return conn.execute(stmt).one_or_none() is not None
