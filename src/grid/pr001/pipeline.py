"""End-to-end PR001 pipeline: parquet -> bronze -> staging -> core (+ pii).

One entry point so the layer order, and the guards between layers, are stated in exactly
one place. Every stage reports counts; the counts reconcile or the run fails.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import structlog
from sqlalchemy import Engine

from grid.db.models import Base
from grid.pr001.bronze import LoadResult, load_bronze
from grid.pr001.core import CoreBuildResult, build_core
from grid.pr001.pdpa import create_shareable_views, populate_pii
from grid.pr001.reference import backfill_row_counts, seed_reference_tables
from grid.pr001.staging import StagingResult, transform_staging

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PipelineReport:
    """Counts at every layer, for the run report."""

    bronze: LoadResult
    staging: StagingResult
    core: CoreBuildResult
    reference_rows: Mapping[str, int]
    pii_rows: int

    @property
    def reconciles(self) -> bool:
        """Whether row counts line up across bronze, staging, core and pii."""
        n = self.bronze.row_count
        return (
            self.staging.rows_out == n
            and self.core.outlets == n
            and self.pii_rows == n
            and sum(self.staging.coord_quality_counts.values()) == n
        )


def create_all(engine: Engine) -> None:
    """Create every table. Migrations are authoritative; this is for tests and offline."""
    Base.metadata.create_all(engine)


def run_pr001_pipeline(
    engine: Engine,
    path: Path,
    *,
    salt: str,
    today: dt.date | None = None,
    ingested_at: dt.datetime | None = None,
) -> PipelineReport:
    """Run the whole PR001 path and return counts at each layer.

    Args:
        engine: Engine with the layer schemas available.
        path: Parquet extract.
        salt: HMAC key for pseudonymising doctor names. Never defaulted.
        today: Reference date for retention. Injectable for determinism.
        ingested_at: Load timestamp. Injectable for determinism.

    Raises:
        SourceShapeError: the extract's column set departs from the contract.
        SourceShrinkageError: the extract has fewer rows than a prior generation.
        UnknownCodeError: a classification code is not declared in a reference table.
        TransformThresholdError: a transform changed more rows than allowed.
    """
    reference_day = today or dt.date.today()

    bronze = load_bronze(engine, path, ingested_at=ingested_at)
    reference_rows = seed_reference_tables(engine)
    backfill_row_counts(engine, bronze.ingest_id)
    staging = transform_staging(engine, bronze.ingest_id, started_at=ingested_at)
    core = build_core(engine, bronze.ingest_id)
    pii_rows = populate_pii(engine, bronze.ingest_id, salt=salt, today=reference_day)
    create_shareable_views(engine)

    report = PipelineReport(
        bronze=bronze,
        staging=staging,
        core=core,
        reference_rows=reference_rows,
        pii_rows=pii_rows,
    )
    log.info(
        "pr001.pipeline.complete",
        bronze_rows=bronze.row_count,
        staging_rows=staging.rows_out,
        core_outlets=core.outlets,
        pii_rows=pii_rows,
        reconciles=report.reconciles,
    )
    return report
