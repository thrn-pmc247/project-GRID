"""Core layer — the modelled incumbent network, chains, mined signals and the KPI view.

Core holds what we concluded, as distinct from what the source said (bronze) and what it
said once typed and cleaned (staging). Three rules hold here:

* `core.provider_outlet` is sourced **only** from staging. Discovery never writes to it;
  discovered clinics live in `core.grid_candidate` and are joined by
  `core.outlet_candidate_link`.
* Chain membership is **inferred with a confidence**, never asserted. A shared name can
  mean a genuine multi-outlet brand or a re-keyed duplicate, and the data cannot tell
  the two apart on its own.
* Every mined signal keeps the raw fragment that produced it, so a human can audit any
  extraction back to the text.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import structlog
from sqlalchemy import Engine, delete, func, insert, select, text
from sqlalchemy.orm import Session

from grid.db.models import (
    CoreChain,
    CoreOutletChainMember,
    CoreProviderCodeSupersession,
    CoreProviderOutlet,
    CoreRemarksSignal,
    StagingProviderOutlet,
)
from grid.pr001.remarks import (
    SupersessionEdge,
    extract_supersessions,
    find_cycles,
    mine_remark,
)

log = structlog.get_logger(__name__)

CHAIN_NAMESPACE: Final = uuid.UUID("2b7f9e64-1c33-5a77-9f10-8d4e6b2a1c05")
SIGNAL_NAMESPACE: Final = uuid.UUID("9a1d3c58-6e21-5b4f-8c72-4f0a9d3e7b16")

MIN_CHAIN_OUTLETS: Final = 2
"""A single outlet is not a chain."""

KPI_VIEW_NAME: Final = "v_kpi_appointments_monthly"


@dataclass(frozen=True, slots=True)
class CoreBuildResult:
    """Counts from one core build, for the load report."""

    outlets: int
    chains: int
    chain_members: int
    remarks_signals: int
    supersession_edges: int
    supersession_cycles: int
    signal_type_counts: Mapping[str, int]


def build_core(engine: Engine, ingest_id: str) -> CoreBuildResult:
    """Build every core table from the current staging generation."""
    outlets = _build_provider_outlets(engine, ingest_id)
    chains, members = _build_chains(engine)
    signals, edges, cycles, type_counts = _build_remarks(engine)
    create_kpi_view(engine)

    result = CoreBuildResult(
        outlets=outlets,
        chains=chains,
        chain_members=members,
        remarks_signals=signals,
        supersession_edges=edges,
        supersession_cycles=cycles,
        signal_type_counts=type_counts,
    )
    log.info("core.build.complete", outlets=outlets, chains=chains, edges=edges)
    return result


def _build_provider_outlets(engine: Engine, ingest_id: str) -> int:
    """Copy the business-classed subset of staging into `core.provider_outlet`.

    Personal-data columns are deliberately absent: they live in `pii.provider_contact`
    and are joined only under elevated access. Free text carrying embedded staff names
    (`remarks`, `sys_admin_remarks`, `website`) is likewise left in staging.
    """
    with Session(engine) as session:
        session.execute(delete(CoreOutletChainMember))
        session.execute(delete(CoreProviderOutlet))
        session.commit()

    stmt = select(StagingProviderOutlet).order_by(StagingProviderOutlet.row_ordinal)
    rows: list[dict[str, object]] = []
    with Session(engine) as session:
        for outlet in session.execute(stmt).scalars():
            rows.append(
                {
                    "provider_code": outlet.provider_code,
                    "row_guid": outlet.row_guid,
                    "name_raw": outlet.name_raw,
                    "name_normalised": outlet.name_normalised,
                    "chain_base_name": outlet.chain_base_name,
                    "branch_qualifier": outlet.branch_qualifier,
                    "address_unit": outlet.address_unit,
                    "address_street": outlet.address_street,
                    "address_locality": outlet.address_locality,
                    "city_canonical": outlet.city_canonical,
                    "postcode_clean": outlet.postcode_clean,
                    "postcode_valid": outlet.postcode_valid,
                    "state_code": outlet.state_code,
                    "postcode_state_mismatch": outlet.postcode_state_mismatch,
                    "latitude_clean": outlet.latitude_clean,
                    "longitude_clean": outlet.longitude_clean,
                    "coord_quality": outlet.coord_quality,
                    "provider_type_code": outlet.provider_type_code,
                    "status_code": outlet.status_code,
                    "pmcare_panel_status": outlet.pmcare_panel_status,
                    "appointment_date": outlet.appointment_date,
                    "termination_date": outlet.termination_date,
                    "suspension_date": outlet.suspension_date,
                    "operating_hours_present": outlet.operating_hours_present,
                    "sourced_from_ingest_id": ingest_id,
                }
            )

    with engine.begin() as conn:
        for start in range(0, len(rows), 2_000):
            conn.execute(insert(CoreProviderOutlet), rows[start : start + 2_000])
    return len(rows)


def _build_chains(engine: Engine) -> tuple[int, int]:
    """Group outlets by `chain_base_name` into inferred chains.

    Confidence reflects how much the grouping actually tells us. A large group under one
    normalised base name is strong evidence of a real brand; a group of two is weak, and
    could as easily be one clinic keyed twice. The outlets are never merged.
    """
    stmt = (
        select(
            CoreProviderOutlet.chain_base_name,
            func.count().label("n"),
        )
        .where(CoreProviderOutlet.chain_base_name.is_not(None))
        .where(CoreProviderOutlet.chain_base_name != "")
        .group_by(CoreProviderOutlet.chain_base_name)
        .having(func.count() >= MIN_CHAIN_OUTLETS)
    )

    with engine.connect() as conn:
        groups = [(str(base), int(n)) for base, n in conn.execute(stmt)]

    variants: defaultdict[str, set[str]] = defaultdict(set)
    members: list[dict[str, object]] = []
    chains: list[dict[str, object]] = []

    with Session(engine) as session:
        session.execute(delete(CoreChain))
        session.commit()

        for base, count in groups:
            chain_id = str(uuid.uuid5(CHAIN_NAMESPACE, base))
            rows = session.execute(
                select(CoreProviderOutlet.provider_code, CoreProviderOutlet.name_raw).where(
                    CoreProviderOutlet.chain_base_name == base
                )
            ).all()
            for code, raw in rows:
                variants[base].add(str(raw or ""))
                members.append(
                    {
                        "provider_code": code,
                        "chain_id": chain_id,
                        "confidence": _chain_confidence(count),
                        "method": "normalised_name_group",
                    }
                )
            chains.append(
                {
                    "chain_id": chain_id,
                    "chain_base_name": base,
                    "outlet_count": count,
                    "name_variants": "|".join(sorted(v for v in variants[base] if v)),
                    "source": "inferred",
                    "notes": (
                        "Grouped on normalised chain base name. INFERRED — a shared name "
                        "may indicate a genuine multi-outlet brand or the same premises "
                        "keyed more than once. Outlets are never merged."
                    ),
                }
            )

    with engine.begin() as conn:
        if chains:
            conn.execute(insert(CoreChain), chains)
        for start in range(0, len(members), 2_000):
            conn.execute(insert(CoreOutletChainMember), members[start : start + 2_000])
    return len(chains), len(members)


def _chain_confidence(outlet_count: int) -> float:
    """Confidence that a name group is a real chain rather than a duplicate.

    Deliberately coarse. Two outlets sharing a name is as likely to be double-keying as
    a brand; twenty is not.
    """
    if outlet_count >= 20:
        return 0.90
    if outlet_count >= 5:
        return 0.70
    if outlet_count >= 3:
        return 0.50
    return 0.30


def _build_remarks(engine: Engine) -> tuple[int, int, int, Mapping[str, int]]:
    """Mine REMARKS into `core.remarks_signal` and `core.provider_code_supersession`."""
    with engine.connect() as conn:
        known_codes = {
            str(code) for (code,) in conn.execute(select(StagingProviderOutlet.provider_code))
        }
        rows = conn.execute(
            select(StagingProviderOutlet.provider_code, StagingProviderOutlet.remarks)
            .where(StagingProviderOutlet.remarks.is_not(None))
            .order_by(StagingProviderOutlet.provider_code)
        ).all()

    signals: list[dict[str, object]] = []
    edges: dict[tuple[str, str], SupersessionEdge] = {}
    type_counts: defaultdict[str, int] = defaultdict(int)

    for provider_code, remark in rows:
        for signal in mine_remark(str(provider_code), remark, known_codes):
            type_counts[signal.signal_type] += 1
            signals.append(
                {
                    "signal_id": str(
                        uuid.uuid5(
                            SIGNAL_NAMESPACE,
                            f"{signal.provider_code}:{signal.pattern_id}:{signal.raw_fragment}",
                        )
                    ),
                    "provider_code": signal.provider_code,
                    "signal_type": signal.signal_type,
                    "extracted_value": signal.extracted_value,
                    "raw_fragment": signal.raw_fragment,
                    "pattern_id": signal.pattern_id,
                    "confidence": signal.confidence,
                }
            )
        for edge in extract_supersessions(str(provider_code), remark, known_codes):
            key = (edge.superseded_code, edge.superseding_code)
            # Keep the highest-confidence evidence when a pair is seen more than once.
            if key not in edges or edge.confidence > edges[key].confidence:
                edges[key] = edge

    cycles = find_cycles(edges.values())

    with Session(engine) as session:
        session.execute(delete(CoreRemarksSignal))
        session.execute(delete(CoreProviderCodeSupersession))
        session.commit()

    # Deduplicate on signal_id — the same fragment can legitimately recur on one row.
    unique_signals = {row["signal_id"]: row for row in signals}

    with engine.begin() as conn:
        batch = list(unique_signals.values())
        for start in range(0, len(batch), 2_000):
            conn.execute(insert(CoreRemarksSignal), batch[start : start + 2_000])
        if edges:
            conn.execute(
                insert(CoreProviderCodeSupersession),
                [
                    {
                        "superseded_code": e.superseded_code,
                        "superseding_code": e.superseding_code,
                        "evidence": e.evidence,
                        "pattern_id": e.pattern_id,
                        "confidence": e.confidence,
                    }
                    for e in edges.values()
                ],
            )

    return len(batch), len(edges), len(cycles), dict(sorted(type_counts.items()))


# --------------------------------------------------------------------------------------
# Task 7 — KPI baseline
# --------------------------------------------------------------------------------------

_KPI_VIEW_SQL: Final = f"""
CREATE VIEW core.{KPI_VIEW_NAME} AS
SELECT
    strftime('%Y-%m', o.appointment_date)          AS appointment_month,
    o.provider_type_code                            AS provider_type_code,
    CASE WHEN o.provider_type_code = 'GP' THEN 1 ELSE 0 END AS is_gp,
    COUNT(*)                                        AS appointments,
    SUM(CASE WHEN o.pmcare_panel_status THEN 1 ELSE 0 END) AS appointments_on_panel
FROM core.provider_outlet AS o
WHERE o.appointment_date IS NOT NULL
  AND o.provider_code NOT IN (
        SELECT s.superseded_code FROM core.provider_code_supersession AS s
  )
GROUP BY appointment_month, o.provider_type_code
"""

_KPI_VIEW_SQL_POSTGRES: Final = f"""
CREATE VIEW core.{KPI_VIEW_NAME} AS
SELECT
    to_char(o.appointment_date, 'YYYY-MM')          AS appointment_month,
    o.provider_type_code                            AS provider_type_code,
    (o.provider_type_code = 'GP')                   AS is_gp,
    COUNT(*)                                        AS appointments,
    COUNT(*) FILTER (WHERE o.pmcare_panel_status)   AS appointments_on_panel
FROM core.provider_outlet AS o
WHERE o.appointment_date IS NOT NULL
  AND o.provider_code NOT IN (
        SELECT s.superseded_code FROM core.provider_code_supersession AS s
  )
GROUP BY 1, 2
"""


def create_kpi_view(engine: Engine) -> None:
    """Create `core.v_kpi_appointments_monthly`.

    Net-new provider appointments per calendar month from `APPOINMENT_DATE`, split by
    provider type, with the GP series separable via `is_gp` — GRID's KPI is GP-specific
    net-new engagement, so the GP series must be readable without disturbing the
    all-types series.

    Rows superseded per the REMARKS miner are excluded, so a clinic that was re-keyed
    under a new provider code is not counted twice.
    """
    sql = _KPI_VIEW_SQL if engine.dialect.name == "sqlite" else _KPI_VIEW_SQL_POSTGRES
    with engine.begin() as conn:
        conn.execute(text(f"DROP VIEW IF EXISTS core.{KPI_VIEW_NAME}"))
        conn.execute(text(sql))


def kpi_series(
    engine: Engine, *, year: int | None = None, gp_only: bool = False
) -> Sequence[tuple[str, str, int, int]]:
    """Read the KPI view.

    Args:
        engine: Engine with core built.
        year: Restrict to one calendar year.
        gp_only: Restrict to the GP series.

    Returns:
        Rows of (month, provider_type_code, appointments, appointments_on_panel).
    """
    clauses = []
    if year is not None:
        clauses.append(f"appointment_month LIKE '{year}-%'")
    if gp_only:
        clauses.append("provider_type_code = 'GP'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        f"SELECT appointment_month, provider_type_code, appointments, appointments_on_panel "
        f"FROM core.{KPI_VIEW_NAME} {where} ORDER BY appointment_month, provider_type_code"
    )
    with engine.connect() as conn:
        return [(str(m), str(t), int(a), int(p)) for m, t, a, p in conn.execute(text(sql))]


def supersession_sample(engine: Engine, limit: int = 20) -> Sequence[tuple[str, str, str, float]]:
    """A sample of supersession edges for human eyeballing.

    Ordered deterministically so the same sample comes back on every run.
    """
    stmt = (
        select(
            CoreProviderCodeSupersession.superseded_code,
            CoreProviderCodeSupersession.superseding_code,
            CoreProviderCodeSupersession.evidence,
            CoreProviderCodeSupersession.confidence,
        )
        .order_by(
            CoreProviderCodeSupersession.confidence.desc(),
            CoreProviderCodeSupersession.superseded_code,
        )
        .limit(limit)
    )
    with engine.connect() as conn:
        return [(str(a), str(b), str(e), float(c)) for a, b, e, c in conn.execute(stmt)]


def kpi_baseline_2026(engine: Engine) -> dict[str, int]:
    """Headline baseline figures the reconciliation report quotes."""
    all_types = sum(a for _, _, a, _ in kpi_series(engine, year=2026))
    gp_only = sum(a for _, _, a, _ in kpi_series(engine, year=2026, gp_only=True))
    return {"appointments_2026_all_types": all_types, "appointments_2026_gp": gp_only}


def build_pii(engine: Engine, ingest_id: str, *, salt: str, today: dt.date) -> int:
    """Populate `pii.provider_contact` from bronze. Kept out of core by design.

    Implemented in `grid.pr001.pdpa` — re-exported here only so the layer build reads in
    one place.
    """
    from grid.pr001.pdpa import populate_pii

    return populate_pii(engine, ingest_id, salt=salt, today=today)
