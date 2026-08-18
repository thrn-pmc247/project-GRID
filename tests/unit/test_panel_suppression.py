"""Tests for Queue B derivation (`grid.panel.suppression`).

Two things are being protected here.

**The point-in-time trap.** Membership must never be decided by `status_code = 'A'`.
`TERMINATION_DATE` in the real extract reaches 2028-08-05, so a row can be flagged
terminated today while having been active for the period being reported on. The
synthetic fixture reproduces that shape deliberately, and a test pins it.

**Routing, not dropping.** A row that looks like a duplicate of an on-panel clinic goes
to a review segment. Dropping it silently would hide a data-quality problem; calling it
would embarrass PNM. Tests assert the funnel reconciles, so nothing can vanish.

Extra rows are inserted into `core.provider_outlet` **after** the pipeline has run,
rather than widening the shared 12-row fixture. That keeps the blast radius at zero: the
integration suite's `EXPECTED_*` constants are derived from the shared fixture and would
all need re-deriving if it grew.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import Engine, insert

from grid.db.models import CoreProviderCodeSupersession, CoreProviderOutlet, CoreRemarksSignal
from grid.panel.suppression import (
    Segment,
    create_queue_b_view,
    queue_b_population,
    suppression_report,
)
from grid.pr001.pipeline import PipelineReport

AS_OF = dt.date(2026, 8, 17)


def _outlet(code: str, **overrides: Any) -> dict[str, Any]:
    """A minimal valid `core.provider_outlet` row: GP, active, off panel."""
    row: dict[str, Any] = {
        "provider_code": code,
        "row_guid": f"00000000-0000-4000-8000-{code[-12:]:0>12}",
        "name_raw": f"KLINIK CONTOH {code}",
        "name_normalised": f"KLINIK CONTOH {code}",
        "chain_base_name": f"KLINIK CONTOH {code}",
        "branch_qualifier": None,
        "address_unit": "NO. 1",
        "address_street": "JALAN CONTOH",
        "address_locality": "TAMAN CONTOH",
        "city_canonical": None,
        "postcode_clean": "40000",
        "postcode_valid": True,
        "state_code": "SL",
        "postcode_state_mismatch": None,
        "latitude_clean": None,
        "longitude_clean": None,
        "coord_quality": "MISSING",
        "provider_type_code": "GP",
        "status_code": "A",
        "pmcare_panel_status": False,
        "appointment_date": dt.datetime(2020, 1, 1),
        "termination_date": None,
        "suspension_date": None,
        "operating_hours_present": False,
        "sourced_from_ingest_id": "00000000-0000-0000-0000-000000000000",
    }
    row.update(overrides)
    return row


@pytest.fixture
def seeded(engine: Engine, pipeline_report: PipelineReport) -> Engine:
    """Core, plus extra outlets covering the segments the shared fixture does not."""
    del pipeline_report  # the fixture's side effect (a built core) is what we need
    rows = [
        # Plain call-list member.
        _outlet("QB0001"),
        # On-panel, active — the collision target and a chain sibling.
        _outlet(
            "QB0002",
            name_normalised="KLINIK BERSAMA",
            chain_base_name="KLINIK BERSAMA",
            pmcare_panel_status=True,
        ),
        # Collides on (name_normalised, postcode_clean) with QB0002 -> review.
        _outlet("QB0003", name_normalised="KLINIK BERSAMA", chain_base_name="KLINIK BERSAMA"),
        # Terminated in the past -> win-back, and still flagged on panel -> conflict.
        _outlet(
            "QB0004",
            status_code="T",
            termination_date=dt.datetime(2025, 3, 1),
            pmcare_panel_status=True,
        ),
        # Terminated in the FUTURE -> still active today, so still Queue B.
        _outlet("QB0005", status_code="T", termination_date=dt.datetime(2028, 1, 15)),
        # Carries a REMARKS signal -> review, never called.
        _outlet("QB0006", name_normalised="KLINIK TUTUP", chain_base_name="KLINIK TUTUP"),
        # Superseded provider code -> excluded outright.
        _outlet("QB0007", name_normalised="KLINIK LAMA", chain_base_name="KLINIK LAMA"),
        # Not a GP -> out of scope entirely.
        _outlet("QB0008", provider_type_code="DT"),
    ]
    with engine.begin() as conn:
        conn.execute(insert(CoreProviderOutlet), rows)
        conn.execute(
            insert(CoreRemarksSignal),
            {
                "signal_id": "00000000-0000-4000-8000-000000000006",
                "provider_code": "QB0006",
                "signal_type": "closed",
                "extracted_value": None,
                "raw_fragment": "CLOSED",
                "pattern_id": "closed.keyword",
                "confidence": 0.7,
            },
        )
        conn.execute(
            insert(CoreProviderCodeSupersession),
            {
                "superseded_code": "QB0007",
                "superseding_code": "QB0001",
                "evidence": "CHANGE TO NEW CODE (QB0001)",
                "pattern_id": "supersede.change_to_paren",
                "confidence": 0.9,
            },
        )
    return engine


def _codes(rows: object) -> set[str]:
    return {r.provider_code for r in rows}  # type: ignore[attr-defined]


def test_funnel_reconciles(seeded: Engine) -> None:
    """Nothing vanishes: every not-on-panel row is called, routed or excluded."""
    report = suppression_report(seeded, as_of=AS_OF)
    assert report.reconciles, (
        f"not_on_panel {report.not_on_panel} != call {report.queue_b_final} "
        f"+ superseded {report.excluded_superseded} "
        f"+ flagged {report.routed_to_review_flagged} "
        f"+ collisions {report.routed_to_review_likely_on_panel}"
    )


def test_future_dated_termination_is_still_active(seeded: Engine) -> None:
    """The trap this whole module exists to avoid.

    `QB0005` carries `status_code='T'` and a 2028 termination date. Testing
    `termination_date IS NULL` would drop it; the point-in-time rule keeps it, because
    the termination has not taken effect yet.
    """
    today = queue_b_population(seeded, as_of=AS_OF)
    assert "QB0005" in _codes(today.call_list)

    after = queue_b_population(seeded, as_of=dt.date(2028, 6, 1))
    assert "QB0005" not in _codes(after.call_list)


def test_status_code_and_point_in_time_disagree_and_the_report_says_so(seeded: Engine) -> None:
    """The two definitions of "active" differ, and the count is surfaced, not hidden."""
    report = suppression_report(seeded, as_of=AS_OF)
    assert report.status_code_disagreements >= 1
    assert report.gp_active_as_of != report.gp_active_status_code_a


def test_on_panel_rows_are_suppressed(seeded: Engine) -> None:
    """Suppression is a filter on an authoritative flag, not a fuzzy match."""
    population = queue_b_population(seeded, as_of=AS_OF)
    assert "QB0002" not in _codes(population.call_list)


def test_collision_with_an_on_panel_row_is_routed_to_review(seeded: Engine) -> None:
    """A probable duplicate is shown to a human, never handed to a caller."""
    population = queue_b_population(seeded, as_of=AS_OF)
    assert "QB0003" not in _codes(population.call_list)
    reviewed = {r.provider_code: r for r in population.review}
    assert reviewed["QB0003"].segment is Segment.REVIEW_LIKELY_ON_PANEL
    assert reviewed["QB0003"].collides_with_provider_code == "QB0002"


def test_remarks_flagged_row_is_routed_to_review(seeded: Engine) -> None:
    """PNM's own note that a clinic closed outranks its status flag."""
    population = queue_b_population(seeded, as_of=AS_OF)
    reviewed = {r.provider_code: r for r in population.review}
    assert "QB0006" not in _codes(population.call_list)
    assert reviewed["QB0006"].segment is Segment.REVIEW_FLAGGED
    assert "closed" in reviewed["QB0006"].review_flags


def test_superseded_code_is_excluded_not_routed(seeded: Engine) -> None:
    """Excluded by the same rule the KPI view applies, so the two cannot disagree."""
    population = queue_b_population(seeded, as_of=AS_OF)
    assert "QB0007" not in _codes(population.call_list)
    assert "QB0007" not in _codes(population.review)
    assert population.report.excluded_superseded >= 1


def test_non_gp_rows_are_out_of_scope(seeded: Engine) -> None:
    """GRID is GP/primary care only (guardrail 7)."""
    population = queue_b_population(seeded, as_of=AS_OF)
    assert "QB0008" not in _codes(population.call_list)


def test_win_back_segment_and_panel_flag_conflict(seeded: Engine) -> None:
    """Recently terminated providers are a different conversation, and the
    flag/status contradiction is surfaced rather than silently resolved."""
    population = queue_b_population(seeded, as_of=AS_OF)
    win = {r.provider_code: r for r in population.win_back}
    assert "QB0004" in win
    assert win["QB0004"].segment is Segment.WIN_BACK
    assert win["QB0004"].panel_flag_conflict is True


def test_chain_foothold_counts_only_active_on_panel_siblings(seeded: Engine) -> None:
    """An on-panel sibling is a warm lead; a long-dead one is not."""
    population = queue_b_population(seeded, as_of=AS_OF)
    by_code = {r.provider_code: r for r in population.review}
    assert by_code["QB0003"].chain_on_panel_outlets == 1


def test_state_filter_narrows_the_queue(seeded: Engine) -> None:
    """Territory filtering, for working one area at a time."""
    assert queue_b_population(seeded, as_of=AS_OF, states=["SL"]).call_list
    assert not queue_b_population(seeded, as_of=AS_OF, states=["ZZ"]).call_list


def test_queue_b_view_is_creatable_and_business_only(seeded: Engine) -> None:
    """The shareable view exposes no restricted column.

    Registering `v_queue_b` in `pdpa.SHAREABLE_VIEWS` means the existing PDPA audit
    covers Queue B with no bespoke test — this asserts the view exists for it to inspect.
    """
    from grid.pr001.pdpa import restricted_columns_in_view

    create_queue_b_view(seeded, as_of=AS_OF)
    assert restricted_columns_in_view(seeded, "v_queue_b") == []
