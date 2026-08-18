"""Bronze landing for the PR001 provider master.

Bronze records what the source said, and nothing else. All 70 columns keep their
original names and types; nothing is coerced, cleaned or dropped — including the columns
that carry no information and the two quarantined columns. Cleaning happens at the
staging boundary, where it can be logged and reviewed.

Loads are **append-only generations**, never upserts. Re-running the same file is a
no-op; a changed file creates a new generation alongside the old one, so a prior extract
remains reconstructable.

Idempotency key is the file's SHA-256. `_ingest_id` is derived deterministically from
that digest (UUID5), so the same bytes always produce the same generation id and a
reload is byte-comparable against its predecessor.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl
import structlog
from sqlalchemy import Engine, func, insert, select, update

from grid.db.models import BronzeGeneration, pr001_provider_master
from grid.pr001.columns import EXPECTED_ROW_COUNT, SOURCE_COLUMNS

log = structlog.get_logger(__name__)

INGEST_NAMESPACE: Final = uuid.UUID("6f9c1c1e-4a1a-5f1e-9d0b-7c2f4a3b5d61")
"""Fixed namespace for deriving `_ingest_id` from a file digest. Never regenerate it —
doing so would orphan every existing generation."""

_INSERT_CHUNK: Final = 2_000


class SourceShapeError(RuntimeError):
    """The source file is not shaped the way the contract says it is.

    Raised rather than tolerated: a column set that has changed silently is exactly the
    drift the profiler and this loader exist to catch.
    """


class SourceShrinkageError(RuntimeError):
    """A newer extract carries materially fewer rows than the one before it.

    Per `docs/context/conventions.md`, a source returning fewer rows is a failure, never
    an empty success.
    """


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Outcome of one bronze load."""

    ingest_id: str
    source_filename: str
    source_sha256: str
    row_count: int
    column_count: int
    rows_inserted: int
    was_noop: bool
    """True when this exact file had already been loaded and nothing was written."""


def sha256_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    """Return the hex SHA-256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def ingest_id_for(source_sha256: str) -> str:
    """Derive the deterministic generation id for a file digest."""
    return str(uuid.uuid5(INGEST_NAMESPACE, source_sha256))


def _assert_source_shape(frame: pl.DataFrame, path: Path) -> None:
    """Fail loudly when the file's column set departs from the contract."""
    actual = tuple(frame.columns)
    if actual == SOURCE_COLUMNS:
        return

    missing = [c for c in SOURCE_COLUMNS if c not in actual]
    unexpected = [c for c in actual if c not in SOURCE_COLUMNS]
    if missing or unexpected:
        raise SourceShapeError(
            f"{path.name}: column set does not match the PR001 contract. "
            f"Missing {missing or 'none'}; unexpected {unexpected or 'none'}. "
            "Update src/grid/pr001/columns.py deliberately if the source really changed."
        )
    raise SourceShapeError(
        f"{path.name}: columns are the expected 70 but in a different order. "
        "Bronze records _row_ordinal against physical order, so this must be reviewed."
    )


def _check_shrinkage(engine: Engine, row_count: int, path: Path) -> None:
    """Raise when this extract has fewer rows than the largest already loaded."""
    with engine.connect() as conn:
        previous = conn.execute(select(func.max(BronzeGeneration.row_count))).scalar()

    baseline = max(previous or 0, EXPECTED_ROW_COUNT if previous is None else 0)
    if baseline and row_count < baseline:
        raise SourceShrinkageError(
            f"{path.name}: {row_count:,} rows against a baseline of {baseline:,} "
            f"({baseline - row_count:,} fewer). A shrinking source is a failure, not an "
            "empty success — confirm the extract is complete before loading."
        )


def load_bronze(
    engine: Engine,
    path: Path,
    *,
    ingested_at: dt.datetime | None = None,
) -> LoadResult:
    """Load a PR001 parquet extract into `bronze.pr001_provider_master`.

    Args:
        engine: Engine with the layer schemas available.
        path: Path to the parquet extract.
        ingested_at: Load timestamp. Injectable so tests are deterministic; defaults to
            the current UTC time. This is the only non-deterministic field written.

    Returns:
        A `LoadResult`. `was_noop` is True when the file had already been loaded.

    Raises:
        SourceShapeError: the column set or order departs from the contract.
        SourceShrinkageError: the extract carries fewer rows than a prior generation.
    """
    stamp = ingested_at or dt.datetime.now(dt.UTC).replace(tzinfo=None)
    digest = sha256_file(path)
    ingest_id = ingest_id_for(digest)

    with engine.connect() as conn:
        already = conn.execute(
            select(BronzeGeneration.ingest_id).where(BronzeGeneration.source_sha256 == digest)
        ).scalar_one_or_none()

    frame = pl.read_parquet(path)
    _assert_source_shape(frame, path)
    row_count, column_count = frame.height, frame.width

    if already is not None:
        log.info(
            "bronze.load.noop",
            ingest_id=already,
            source_filename=path.name,
            row_count=row_count,
        )
        return LoadResult(
            ingest_id=already,
            source_filename=path.name,
            source_sha256=digest,
            row_count=row_count,
            column_count=column_count,
            rows_inserted=0,
            was_noop=True,
        )

    _check_shrinkage(engine, row_count, path)

    records = _to_records(frame, ingest_id=ingest_id, stamp=stamp, path=path, digest=digest)

    with engine.begin() as conn:
        conn.execute(update(BronzeGeneration).values(is_current=False))
        for start in range(0, len(records), _INSERT_CHUNK):
            conn.execute(pr001_provider_master.insert(), records[start : start + _INSERT_CHUNK])
        conn.execute(
            insert(BronzeGeneration),
            {
                "ingest_id": ingest_id,
                "source_filename": path.name,
                "source_sha256": digest,
                "source_bytes": path.stat().st_size,
                "row_count": row_count,
                "column_count": column_count,
                "ingested_at": stamp,
                "is_current": True,
            },
        )

    log.info(
        "bronze.load.complete",
        ingest_id=ingest_id,
        source_filename=path.name,
        row_count=row_count,
        column_count=column_count,
    )
    return LoadResult(
        ingest_id=ingest_id,
        source_filename=path.name,
        source_sha256=digest,
        row_count=row_count,
        column_count=column_count,
        rows_inserted=len(records),
        was_noop=False,
    )


def _to_records(
    frame: pl.DataFrame,
    *,
    ingest_id: str,
    stamp: dt.datetime,
    path: Path,
    digest: str,
) -> Sequence[dict[str, object]]:
    """Convert the frame to insertable rows, adding the five audit columns.

    `_row_ordinal` is the row's position in the source file. PR001 has no meaningful
    sort order, so physical position is the only stable way to line two generations up
    against each other.
    """
    rows = frame.to_dicts()
    return [
        {
            "_ingest_id": ingest_id,
            "_row_ordinal": ordinal,
            "_ingested_at": stamp,
            "_source_filename": path.name,
            "_source_sha256": digest,
            **row,
        }
        for ordinal, row in enumerate(rows)
    ]


def current_generation(engine: Engine) -> BronzeGeneration | None:
    """Return the generation marked current, or None when bronze is empty."""
    with engine.connect() as conn:
        row = conn.execute(
            select(BronzeGeneration).where(BronzeGeneration.is_current.is_(True))
        ).one_or_none()
    if row is None:
        return None
    return BronzeGeneration(**row._mapping)
