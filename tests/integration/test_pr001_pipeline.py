"""End-to-end tests for the PR001 pipeline: parquet -> bronze -> staging -> core (+ pii).

The pipeline's contract is that its counts reconcile or the run fails, so these tests
assert the reconciliation directly and then probe the specific behaviours that a count
alone would not catch:

* **Idempotency.** A reload of the same bytes is a no-op with the same generation id,
  because `_ingest_id` is a UUID5 of the file digest.
* **The key discipline.** `provider_code` and `row_guid` are the only two safe keys and
  carry unique constraints; `mix_row_id` collides in the source and therefore carries no
  constraint at all. Both halves are asserted — a constraint quietly added to `mix_row_id`
  would break a future load of the real extract, where 15 rows collide.
* **Point-in-time status.** `TERMINATION_DATE` reaches 2028, so a row can be flagged
  terminated today while having been active for the month being reported on. Testing
  `termination_date IS NULL` would silently return the wrong answer.
* **The KPI baseline.** Superseded provider codes are excluded, so a clinic re-keyed under
  a new code is not counted twice.

Everything runs on the synthetic fixture in `tests/conftest.py`. The one test that needs
the real `PR001.parquet` skips itself when the file is absent — it is gitignored
(CLAUDE.md guardrail 5), so CI never has it.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Final

import polars as pl
import pytest
from sqlalchemy import Engine, func, insert, select, text
from sqlalchemy.exc import IntegrityError

from grid.db.engine import make_engine
from grid.db.models import (
    CoreProviderCodeSupersession,
    CoreProviderOutlet,
    OpsLoadLog,
    PiiProviderContact,
    StagingProviderOutlet,
    pr001_provider_master,
)
from grid.normalise.coordinates import CoordQuality
from grid.pr001.bronze import SourceShapeError, SourceShrinkageError, load_bronze
from grid.pr001.core import kpi_baseline_2026, kpi_series
from grid.pr001.pipeline import PipelineReport, create_all, run_pr001_pipeline
from grid.pr001.staging import is_active_as_of

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
REAL_PARQUET: Final = REPO_ROOT / "PR001.parquet"

SYNTHETIC_ROWS: Final = 12

EXPECTED_COORD_COUNTS: Final[dict[str, int]] = {
    CoordQuality.MISSING.value: 8,
    CoordQuality.NULL_ISLAND.value: 1,
    CoordQuality.OUT_OF_BOUNDS.value: 1,
    CoordQuality.REPAIRED_DECIMAL.value: 1,
    CoordQuality.REPAIRED_SPLIT.value: 0,
    CoordQuality.VALID.value: 1,
}
"""The verdicts the twelve crafted rows must produce, verdict by verdict."""

EXPECTED_SENTINEL_REMAPS: Final = 1
EXPECTED_HOURS_PRESENT: Final = 1
EXPECTED_INVALID_POSTCODES: Final = 1
EXPECTED_CHAINS: Final = 1
EXPECTED_CHAIN_MEMBERS: Final = 2

FUTURE_TERMINATED_CODE: Final = "GRIDGP0006"
"""Row 5: `STATUS_CODE='T'` with a termination dated 2028-01-15."""

TERMINATION_TAKES_EFFECT: Final = dt.date(2028, 1, 15)

KPI_2026_ALL_TYPES: Final = 8
KPI_2026_GP: Final = 6
SUPERSEDED_FOR_KPI: Final = "GRIDGP0001"
"""Row 0: appointed 2026-01-15 as a GP, so superseding it must drop both KPI series."""

# The real extract's headline figures, from docs/reconciliation-pr001.md. Asserted only
# where the extract is present.
REAL_EXPECTATIONS: Final[dict[str, Any]] = {
    "rows": 33_643,
    "columns": 70,
    "coord_quality": {
        CoordQuality.MISSING.value: 17_525,
        CoordQuality.NULL_ISLAND.value: 6_210,
        CoordQuality.OUT_OF_BOUNDS.value: 18,
        CoordQuality.REPAIRED_DECIMAL.value: 12,
        CoordQuality.REPAIRED_SPLIT.value: 0,
        CoordQuality.VALID.value: 9_878,
    },
    "chains": 4_122,
    "chain_members": 14_327,
    "remarks_signals": 2_633,
    "supersession_edges": 96,
    "supersession_cycles": 0,
    "kpi_2026_all_types": 1_108,
    "kpi_2026_gp": 423,
}


def _count(engine: Engine, table: Any) -> int:
    """Row count of a table or model.

    Args:
        engine: Engine to query.
        table: A mapped class or `Table`.

    Returns:
        The row count.
    """
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar_one())


def _staging_row(**overrides: object) -> dict[str, object]:
    """A minimal, valid `staging.provider_outlet` row.

    Only the non-nullable columns are stated; everything else takes its column default or
    stays NULL. Used to probe the table's constraints directly, without going through the
    transform.

    Args:
        **overrides: Column values to replace.

    Returns:
        The row as an insertable mapping.
    """
    row: dict[str, object] = {
        "provider_code": "GRIDXX9001",
        "row_guid": "00000000-0000-4000-8000-999999999001",
        "ingest_id": "00000000-0000-0000-0000-000000000000",
        "row_ordinal": 9_001,
        "mix_row_id": 16_170,
        "provider_type_code": "GP",
        "category_code": "P",
        "payment_method_code": "C",
        "status_code": "A",
        "state_code": "SL",
        "coord_quality": CoordQuality.MISSING.value,
        "pmcare_panel_status": False,
        "city_unmatched": False,
        "postcode_valid": False,
        "operating_hours_present": False,
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------------------------
# Reconciliation across the four layers
# --------------------------------------------------------------------------------------


def test_counts_reconcile_across_every_layer(
    engine: Engine, pipeline_report: PipelineReport
) -> None:
    """Bronze, staging, core and pii all hold one row per source row."""
    assert pipeline_report.bronze.row_count == SYNTHETIC_ROWS
    assert pipeline_report.bronze.column_count == 70
    assert pipeline_report.staging.rows_in == SYNTHETIC_ROWS
    assert pipeline_report.staging.rows_out == SYNTHETIC_ROWS
    assert pipeline_report.core.outlets == SYNTHETIC_ROWS
    assert pipeline_report.pii_rows == SYNTHETIC_ROWS

    assert _count(engine, pr001_provider_master) == SYNTHETIC_ROWS
    assert _count(engine, StagingProviderOutlet) == SYNTHETIC_ROWS
    assert _count(engine, CoreProviderOutlet) == SYNTHETIC_ROWS
    assert _count(engine, PiiProviderContact) == SYNTHETIC_ROWS


def test_report_reconciles(pipeline_report: PipelineReport) -> None:
    """The report's own reconciliation verdict is True."""
    assert pipeline_report.reconciles is True


def test_coord_quality_counts_sum_to_the_row_count(
    engine: Engine, pipeline_report: PipelineReport
) -> None:
    """Every row gets exactly one coordinate verdict, and every verdict is accounted for.

    The counts are zero-filled across the whole enum so a caller can reconcile to a known
    total without guarding for absent keys — which is why `REPAIRED_SPLIT` must be present
    as a zero rather than missing.
    """
    counts = pipeline_report.staging.coord_quality_counts

    assert set(counts) == {quality.value for quality in CoordQuality}, (
        "every verdict must appear as a key, including the ones with no rows"
    )
    assert sum(counts.values()) == SYNTHETIC_ROWS
    assert dict(counts) == EXPECTED_COORD_COUNTS

    with engine.connect() as conn:
        stored = dict(
            conn.execute(
                select(StagingProviderOutlet.coord_quality, func.count()).group_by(
                    StagingProviderOutlet.coord_quality
                )
            ).all()
        )
    assert stored == {quality: count for quality, count in EXPECTED_COORD_COUNTS.items() if count}


def test_repaired_row_keeps_clean_values_and_a_repair_note(
    engine: Engine, pipeline_report: PipelineReport
) -> None:
    """A repaired row records what was done to it; an unrepairable one records nothing."""
    with engine.connect() as conn:
        repaired = conn.execute(
            select(
                StagingProviderOutlet.latitude_clean,
                StagingProviderOutlet.longitude_clean,
                StagingProviderOutlet.coord_repair_note,
            ).where(StagingProviderOutlet.coord_quality == CoordQuality.REPAIRED_DECIMAL.value)
        ).one()
        unrepairable = conn.execute(
            select(
                StagingProviderOutlet.latitude_clean,
                StagingProviderOutlet.longitude_clean,
                StagingProviderOutlet.coord_repair_note,
            ).where(StagingProviderOutlet.coord_quality == CoordQuality.OUT_OF_BOUNDS.value)
        ).one()

    latitude, longitude, note = repaired
    assert latitude == pytest.approx(3.112491)
    assert longitude == pytest.approx(101.591143)
    assert note is not None and "decimal shift" in note

    assert unrepairable == (None, None, None), (
        "an unrepairable pair keeps no coordinates and claims no repair"
    )


def test_sentinel_and_operating_hours_counts(
    engine: Engine, pipeline_report: PipelineReport
) -> None:
    """The 1900-01-01 sentinel is remapped to NULL, and all-midnight hours read as unset."""
    assert pipeline_report.staging.acc_vendor_sentinel_remapped == EXPECTED_SENTINEL_REMAPS
    assert pipeline_report.staging.operating_hours_present == EXPECTED_HOURS_PRESENT
    assert pipeline_report.staging.postcode_invalid == EXPECTED_INVALID_POSTCODES

    with engine.connect() as conn:
        sentinel_survivors = conn.execute(
            select(func.count())
            .select_from(StagingProviderOutlet)
            .where(StagingProviderOutlet.acc_vendor_flag_date.is_not(None))
        ).scalar_one()
        hours_present = conn.execute(
            select(func.count())
            .select_from(StagingProviderOutlet)
            .where(StagingProviderOutlet.operating_hours_present.is_(True))
        ).scalar_one()

    assert sentinel_survivors == 0, "no 1900-01-01 value may survive into staging"
    assert hours_present == EXPECTED_HOURS_PRESENT


def test_invalid_postcode_is_rejected_not_repaired(
    engine: Engine, pipeline_report: PipelineReport
) -> None:
    """A six-digit postcode is kept raw, flagged invalid, and never truncated."""
    with engine.connect() as conn:
        raw, clean, valid = conn.execute(
            select(
                StagingProviderOutlet.postcode_raw,
                StagingProviderOutlet.postcode_clean,
                StagingProviderOutlet.postcode_valid,
            )
            .where(StagingProviderOutlet.postcode_valid.is_(False))
            .where(StagingProviderOutlet.postcode_raw.is_not(None))
        ).one()

    assert raw == "814000"
    assert clean is None, "an invalid postcode must not be truncated to five digits"
    assert valid is False


def test_chains_are_inferred_from_the_shared_base_name(
    pipeline_report: PipelineReport,
) -> None:
    """Two outlets sharing a base name after suffix stripping form one inferred chain."""
    assert pipeline_report.core.chains == EXPECTED_CHAINS
    assert pipeline_report.core.chain_members == EXPECTED_CHAIN_MEMBERS


def test_staff_identities_are_case_folded(pipeline_report: PipelineReport) -> None:
    """`M_NOOR` and `m_noor` are one person, and the collision is counted."""
    assert pipeline_report.staging.user_case_collisions == 1


def test_reference_tables_are_seeded(pipeline_report: PipelineReport) -> None:
    """Every vocabulary is seeded as part of the run."""
    assert pipeline_report.reference_rows["ref_provider_type"] == 21
    assert pipeline_report.reference_rows["ref_state"] == 18
    assert pipeline_report.reference_rows["ref_status"] == 4


# --------------------------------------------------------------------------------------
# Bronze idempotency
# --------------------------------------------------------------------------------------


def test_bronze_reload_is_a_noop(
    engine: Engine, synthetic_parquet: Path, synthetic_calibration: None
) -> None:
    """Reloading the same bytes writes nothing and reuses the same generation id.

    `_ingest_id` is a UUID5 of the file's SHA-256, so identical bytes always produce the
    identical generation. A second load must therefore be recognised rather than appended,
    or every re-run would double the layer.
    """
    first = load_bronze(engine, synthetic_parquet)
    rows_after_first = _count(engine, pr001_provider_master)

    second = load_bronze(engine, synthetic_parquet)
    rows_after_second = _count(engine, pr001_provider_master)

    assert first.was_noop is False
    assert first.rows_inserted == SYNTHETIC_ROWS
    assert second.was_noop is True, "a reload of identical bytes must be a no-op"
    assert second.rows_inserted == 0
    assert second.ingest_id == first.ingest_id, "the generation id must be reproducible"
    assert second.source_sha256 == first.source_sha256
    assert rows_after_second == rows_after_first == SYNTHETIC_ROWS, "bronze must not grow"


def _load_log_rows(engine: Engine, load_id: str) -> int:
    """Rows in ops.load_log for one load id."""
    with engine.connect() as conn:
        return int(
            conn.execute(
                select(func.count())
                .select_from(OpsLoadLog.__table__)
                .where(OpsLoadLog.load_id == load_id)
            ).scalar_one()
        )


def test_whole_pipeline_is_rerunnable(
    engine: Engine, synthetic_parquet: Path, synthetic_calibration: None, synthetic_salt: str
) -> None:
    """Running the pipeline twice leaves the same counts, not doubled ones.

    The monthly refresh runbook re-runs the pipeline, and so does any retry after a
    partial failure, so re-runnability is an operational requirement rather than a
    nicety. Staging deletes and rebuilds its rows and its own accounting in
    `ops.load_log` / `ops.transform_log` (replace-on-rebuild); the append-only record of
    what arrived stays in `bronze.pr001_generation`.
    """
    first = run_pr001_pipeline(engine, synthetic_parquet, salt=synthetic_salt)
    second = run_pr001_pipeline(engine, synthetic_parquet, salt=synthetic_salt)

    assert second.bronze.was_noop is True
    assert second.reconciles is True
    assert second.staging.rows_out == first.staging.rows_out == SYNTHETIC_ROWS
    assert second.core.outlets == first.core.outlets == SYNTHETIC_ROWS
    assert second.pii_rows == first.pii_rows == SYNTHETIC_ROWS
    assert _count(engine, pr001_provider_master) == SYNTHETIC_ROWS
    assert _count(engine, PiiProviderContact) == SYNTHETIC_ROWS

    # The staging load log is replaced, not appended: exactly one row for this load.
    assert first.staging.load_id == second.staging.load_id
    assert _load_log_rows(engine, second.staging.load_id) == 1


# --------------------------------------------------------------------------------------
# The key discipline
# --------------------------------------------------------------------------------------


def test_provider_code_is_unique(engine: Engine, pipeline_report: PipelineReport) -> None:
    """`provider_code` is one of only two safe keys, so a duplicate must be rejected."""
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(StagingProviderOutlet),
            _staging_row(
                provider_code="GRIDGP0001",
                row_guid="00000000-0000-4000-8000-999999999999",
            ),
        )


def test_row_guid_is_unique(engine: Engine, pipeline_report: PipelineReport) -> None:
    """`row_guid` is the second safe key and carries its own unique constraint."""
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            insert(StagingProviderOutlet),
            _staging_row(
                provider_code="GRIDXX9999",
                row_guid="00000000-0000-4000-8000-000000000000",
            ),
        )


def test_mix_row_id_carries_no_unique_constraint(
    engine: Engine, pipeline_report: PipelineReport
) -> None:
    """Two staging rows may share a `mix_row_id`, and this must not raise.

    `MIX_ROW_ID` is NOT a key: 15 rows collide in the real extract's 16,170-16,192 range.
    It is retained as a nullable, unindexed passthrough. A unique constraint added here
    would look harmless in a test and then fail the next load of the real extract, so the
    absence of the constraint is asserted rather than assumed.
    """
    shared_id = 424_242
    with engine.begin() as conn:
        conn.execute(
            insert(StagingProviderOutlet),
            _staging_row(
                provider_code="GRIDXX9101",
                row_guid="00000000-0000-4000-8000-999999999101",
                row_ordinal=9_101,
                mix_row_id=shared_id,
            ),
        )
        conn.execute(
            insert(StagingProviderOutlet),
            _staging_row(
                provider_code="GRIDXX9102",
                row_guid="00000000-0000-4000-8000-999999999102",
                row_ordinal=9_102,
                mix_row_id=shared_id,
            ),
        )

    with engine.connect() as conn:
        sharing = conn.execute(
            select(func.count())
            .select_from(StagingProviderOutlet)
            .where(StagingProviderOutlet.mix_row_id == shared_id)
        ).scalar_one()
    assert sharing == 2

    constrained = {
        constraint.columns.keys()[0]
        for constraint in StagingProviderOutlet.__table__.constraints
        if hasattr(constraint, "columns") and len(constraint.columns) == 1
    }
    assert "mix_row_id" not in constrained
    assert not any(
        "mix_row_id" in index.columns for index in StagingProviderOutlet.__table__.indexes
    ), "mix_row_id must stay unindexed — it is never used in a join"


# --------------------------------------------------------------------------------------
# Point-in-time status
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("as_of", "expected", "why"),
    [
        (dt.date(2026, 8, 17), True, "the termination has not yet taken effect"),
        (TERMINATION_TAKES_EFFECT - dt.timedelta(days=1), True, "the day before it bites"),
        (TERMINATION_TAKES_EFFECT, False, "the day it takes effect"),
        (dt.date(2029, 1, 1), False, "well after it took effect"),
        (dt.date(2019, 1, 1), False, "before the provider was even appointed"),
    ],
)
def test_is_active_as_of_respects_a_future_dated_termination(
    engine: Engine,
    pipeline_report: PipelineReport,
    as_of: dt.date,
    expected: bool,
    why: str,
) -> None:
    """A future-dated termination does not make a provider inactive today.

    `TERMINATION_DATE` reaches 2028-08-05 in the real extract, so `termination_date IS
    NULL` is the wrong test for activity — it would report this provider inactive for
    every historical month, and would get worse as future-dated terminations accumulate.
    """
    assert is_active_as_of(engine, FUTURE_TERMINATED_CODE, as_of) is expected, why


def test_is_active_as_of_is_false_for_an_unknown_code(
    engine: Engine, pipeline_report: PipelineReport
) -> None:
    """A code that is not in staging is not active — never an error, never True."""
    assert is_active_as_of(engine, "NOT_A_PROVIDER", dt.date(2026, 8, 17)) is False


def test_suspension_also_ends_activity(engine: Engine, pipeline_report: PipelineReport) -> None:
    """A suspension that has taken effect ends activity just as a termination does."""
    assert is_active_as_of(engine, "GRIDSP0010", dt.date(2025, 12, 31)) is True
    assert is_active_as_of(engine, "GRIDSP0010", dt.date(2026, 1, 5)) is False


# --------------------------------------------------------------------------------------
# The KPI baseline
# --------------------------------------------------------------------------------------


def test_kpi_view_reports_appointments_by_month_and_type(
    engine: Engine, pipeline_report: PipelineReport
) -> None:
    """The KPI view splits appointments by month and provider type, GP separably."""
    all_types = kpi_series(engine, year=2026)
    gp_only = kpi_series(engine, year=2026, gp_only=True)

    assert sum(count for _, _, count, _ in all_types) == KPI_2026_ALL_TYPES
    assert sum(count for _, _, count, _ in gp_only) == KPI_2026_GP
    assert {code for _, code, _, _ in gp_only} == {"GP"}
    assert kpi_baseline_2026(engine) == {
        "appointments_2026_all_types": KPI_2026_ALL_TYPES,
        "appointments_2026_gp": KPI_2026_GP,
    }


def test_kpi_view_excludes_superseded_codes(
    engine: Engine, pipeline_report: PipelineReport
) -> None:
    """A superseded provider code drops out of the KPI series.

    REMARKS is PNM telling us which records are the same clinic. A clinic re-keyed under a
    new provider code would otherwise be counted twice — once per code — inflating the
    net-new figure the engagement KPI is measured against.
    """
    before = kpi_baseline_2026(engine)
    assert before["appointments_2026_all_types"] == KPI_2026_ALL_TYPES
    assert before["appointments_2026_gp"] == KPI_2026_GP

    with engine.begin() as conn:
        conn.execute(
            insert(CoreProviderCodeSupersession),
            {
                "superseded_code": SUPERSEDED_FOR_KPI,
                "superseding_code": "GRIDGP0002",
                "evidence": "CHANGE TO NEW CODE (GRIDGP0002)",
                "pattern_id": "supersede.change_to_paren",
                "confidence": 0.90,
            },
        )

    after = kpi_baseline_2026(engine)
    assert after["appointments_2026_all_types"] == KPI_2026_ALL_TYPES - 1
    assert after["appointments_2026_gp"] == KPI_2026_GP - 1

    months = {month for month, _, _, _ in kpi_series(engine, year=2026, gp_only=True)}
    assert "2026-01" not in months, "the superseded row's month must disappear entirely"


def test_supersession_graph_is_acyclic_on_the_fixture(
    pipeline_report: PipelineReport,
) -> None:
    """The fixture's remarks are mined without producing an edge or a cycle.

    Cycles are legitimate in the real graph — two rows each pointing at the other — so
    consumers must handle them. This asserts only that the miner reports the count.
    """
    assert pipeline_report.core.supersession_edges == 0
    assert pipeline_report.core.supersession_cycles == 0
    assert pipeline_report.core.remarks_signals == 3
    assert dict(pipeline_report.core.signal_type_counts) == {
        "closed": 1,
        "duplicate_flag": 1,
        "file_or_onboarding_date": 1,
    }


def test_core_is_sourced_only_from_staging(engine: Engine, pipeline_report: PipelineReport) -> None:
    """Every core outlet is stamped with the bronze generation it came from."""
    with engine.connect() as conn:
        generations = {
            row[0]
            for row in conn.execute(select(CoreProviderOutlet.sourced_from_ingest_id).distinct())
        }
    assert generations == {pipeline_report.bronze.ingest_id}


# --------------------------------------------------------------------------------------
# The real extract — skipped wherever it is absent
# --------------------------------------------------------------------------------------


def test_real_extract_reproduces_the_documented_figures(synthetic_salt: str) -> None:
    """The real extract still produces the figures `docs/reconciliation-pr001.md` quotes.

    Skipped in CI and on any machine without the extract: `PR001.parquet` is gitignored
    under guardrail 5 and is never committed. Where it *is* present this is the strongest
    guard the suite has — it pins the pipeline's whole observable output, so a refactor
    that changes a count cannot pass quietly.
    """
    if not REAL_PARQUET.is_file():
        pytest.skip(f"{REAL_PARQUET.name} is absent (gitignored); synthetic coverage applies")

    engine = make_engine()
    try:
        create_all(engine)
        report = run_pr001_pipeline(
            engine,
            REAL_PARQUET,
            salt=synthetic_salt,
            today=dt.date(2026, 8, 17),
            ingested_at=dt.datetime(2026, 8, 17, 9, 0, 0),
        )

        assert report.reconciles is True
        assert report.bronze.row_count == REAL_EXPECTATIONS["rows"]
        assert report.bronze.column_count == REAL_EXPECTATIONS["columns"]
        assert report.staging.rows_out == REAL_EXPECTATIONS["rows"]
        assert report.core.outlets == REAL_EXPECTATIONS["rows"]
        assert report.pii_rows == REAL_EXPECTATIONS["rows"]

        assert dict(report.staging.coord_quality_counts) == REAL_EXPECTATIONS["coord_quality"]
        assert sum(report.staging.coord_quality_counts.values()) == REAL_EXPECTATIONS["rows"]

        assert report.core.chains == REAL_EXPECTATIONS["chains"]
        assert report.core.chain_members == REAL_EXPECTATIONS["chain_members"]
        assert report.core.remarks_signals == REAL_EXPECTATIONS["remarks_signals"]
        assert report.core.supersession_edges == REAL_EXPECTATIONS["supersession_edges"]
        assert report.core.supersession_cycles == REAL_EXPECTATIONS["supersession_cycles"]

        assert kpi_baseline_2026(engine) == {
            "appointments_2026_all_types": REAL_EXPECTATIONS["kpi_2026_all_types"],
            "appointments_2026_gp": REAL_EXPECTATIONS["kpi_2026_gp"],
        }
    finally:
        engine.dispose()


def test_synthetic_fixture_never_stands_in_for_the_real_extract(
    synthetic_parquet: Path,
) -> None:
    """The fixture is recognisably synthetic, so it can never be mistaken for the extract.

    Guardrail 5: no real clinic data in the repository. The fixture is written under
    `tmp_path`, never committed, and every provider name says so.
    """
    frame = pl.read_parquet(synthetic_parquet)
    names = frame.get_column("PROVIDER_DESCRIPTION").to_list()

    assert frame.height == SYNTHETIC_ROWS
    assert all("CONTOH" in name for name in names), (
        "every synthetic clinic name must be obviously fabricated"
    )
    assert synthetic_parquet.name != REAL_PARQUET.name


def test_bronze_rejects_a_frame_whose_columns_do_not_match(
    engine: Engine, tmp_path: Path, synthetic_frame: pl.DataFrame, synthetic_calibration: None
) -> None:
    """A source whose column set has drifted fails the load rather than being tolerated."""
    truncated = tmp_path / "PR001_missing_column.parquet"
    synthetic_frame.drop("PROVIDER_CODE").write_parquet(truncated)

    with pytest.raises(SourceShapeError, match="PROVIDER_CODE"):
        load_bronze(engine, truncated)


def test_bronze_rejects_a_shrinking_source(
    engine: Engine,
    synthetic_parquet: Path,
    tmp_path: Path,
    synthetic_frame: pl.DataFrame,
    synthetic_calibration: None,
) -> None:
    """A newer extract with fewer rows than a prior generation is a failure.

    Per `docs/context/conventions.md` a source returning fewer rows is never an empty
    success. The baseline here is the twelve-row generation already loaded, so this
    exercises the generation-to-generation comparison rather than the initial constant.
    """
    load_bronze(engine, synthetic_parquet)

    shrunk = tmp_path / "PR001_shrunk.parquet"
    synthetic_frame.head(3).write_parquet(shrunk)

    with pytest.raises(SourceShrinkageError, match="shrinking source"):
        load_bronze(engine, shrunk)


def test_ops_logs_record_the_transform_accounting(
    engine: Engine, pipeline_report: PipelineReport
) -> None:
    """Every named transform is accounted for in `ops.transform_log`, none breached."""
    with engine.connect() as conn:
        logged = dict(
            conn.execute(text("SELECT transform_name, rows_changed FROM ops.transform_log")).all()
        )
        loads = conn.execute(text("SELECT COUNT(*) FROM ops.load_log")).scalar_one()
        breached = conn.execute(
            text("SELECT transform_name FROM ops.transform_log WHERE breached")
        ).all()

    assert loads >= 1
    assert logged["acc_vendor_sentinel_to_null"] == EXPECTED_SENTINEL_REMAPS
    assert logged["postcode_invalid"] == EXPECTED_INVALID_POSTCODES
    assert logged["coordinate_repair"] == EXPECTED_COORD_COUNTS[CoordQuality.REPAIRED_DECIMAL.value]
    assert not breached, f"transforms reported as runaway: {breached}"
