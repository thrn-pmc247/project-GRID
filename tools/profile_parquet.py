"""Deterministic parquet profiler.

Emits a byte-for-byte reproducible JSON profile of a parquet file: one entry per
column carrying its storage type, logical type, null/blank/real counts, distinct
count and — where the PDPA contract permits — ordered bounds and a small value
histogram. The profile of `PR001.parquet` is committed as
`tests/fixtures/pr001_profile.json` and diffed by
`tests/unit/test_pr001_profile_drift.py`, so a refreshed extract that loses fill
surfaces as a failing test rather than as a quietly wrong fill rate downstream.

Three rules make the output trustworthy:

* **Blanks are counted apart from nulls.** PR001 records "no value" as an empty
  or whitespace-only string far more often than as NULL — `WEBSITE` holds 19,852
  blanks against 13,708 NULLs, leaving 83 real values out of 33,643. Any fill
  rate that subtracts only NULLs is wrong by two orders of magnitude here.
* **Values are suppressed by two independent controls** (see `_value_suppression`).
  Counts always survive both — they are aggregates, and they are what the
  shrinkage detector runs on.
* **Nothing varies between runs.** No timestamps, no run IDs, no absolute paths;
  sorted keys, fixed float rounding and an explicit `\\n` line ending. Two runs
  over the same bytes produce the same bytes.

Polars is the only reader used: pyarrow is deliberately absent from this
environment and pandas cannot read parquet without it.

Usage:
    python tools/profile_parquet.py PR001.parquet -o tests/fixtures/pr001_profile.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import polars as pl
from polars.datatypes import DataTypeClass

from grid.pr001.columns import SPEC_BY_NAME, LogicalType, is_restricted

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

PROFILE_SCHEMA_VERSION: Final = 1
"""Bump whenever the shape of the emitted profile changes; the drift test asserts it."""

TOP_VALUES_MAX_DISTINCT: Final = 25
"""Columns at or below this many non-null distinct values get a full histogram."""

FLOAT_ROUND_DP: Final = 10
"""Decimal places kept on float bounds, so repeated runs cannot differ in the last bits."""

SUPPRESSION_PDPA: Final = "pdpa"
"""`values_suppressed` marker for the PDPA control — personal data must not be disclosed."""

SUPPRESSION_FREE_TEXT: Final = "free_text"
"""`values_suppressed` marker for the guardrail-5 control — real clinic data must not be
committed. Kept distinct from the PDPA marker so the two controls stay legible: a column
can fail either test for quite different reasons."""

_SHA256_CHUNK_BYTES: Final = 1 << 20

_DERIVED_LOGICAL_TYPES: Final[Mapping[DataTypeClass, LogicalType]] = {
    pl.String: LogicalType.STRING,
    pl.Boolean: LogicalType.BOOLEAN,
    pl.Int64: LogicalType.INT64,
    pl.Float64: LogicalType.DOUBLE,
    pl.Time: LogicalType.TIME_NANOS,
}


def _sha256(path: Path) -> str:
    """Hash a file's bytes.

    Args:
        path: File to hash.

    Returns:
        Lowercase hexadecimal SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_SHA256_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _derive_logical_type(dtype: pl.DataType) -> str:
    """Derive a parquet logical type from a polars dtype.

    Used only for columns absent from the PR001 contract; known columns take their
    logical type from `ColumnSpec.logical_type` so the contract stays authoritative.

    Args:
        dtype: The polars dtype as reported for the column.

    Returns:
        The logical type name, or an `UNMAPPED(...)` marker for a dtype this
        profiler has no mapping for. The marker is deliberately visible rather
        than silently guessed.
    """
    if isinstance(dtype, pl.Datetime):
        adjusted = "UTC-adjusted" if dtype.time_zone is not None else "not UTC-adjusted"
        return f"TIMESTAMP({dtype.time_unit}, {adjusted})"
    mapped = _DERIVED_LOGICAL_TYPES.get(dtype.base_type())
    return str(mapped) if mapped is not None else f"UNMAPPED({dtype})"


def _logical_type(name: str, dtype: pl.DataType) -> str:
    """Resolve the logical type of a column, preferring the PR001 contract.

    Args:
        name: Column name.
        dtype: The polars dtype as reported for the column.

    Returns:
        The logical type name.
    """
    spec = SPEC_BY_NAME.get(name)
    return str(spec.logical_type) if spec is not None else _derive_logical_type(dtype)


def _is_ordered(dtype: pl.DataType) -> bool:
    """Whether `min`/`max` are meaningful for a dtype.

    Numeric, temporal and string columns are ordered. Booleans are not — their
    `top_values` histogram carries the same information more usefully.

    Args:
        dtype: The polars dtype as reported for the column.

    Returns:
        True when bounds should be emitted.
    """
    return bool(dtype.is_numeric() or dtype.is_temporal() or dtype == pl.String)


def _json_scalar(value: object) -> JsonScalar:
    """Normalise a polars scalar into a JSON-serialisable, run-stable value.

    Args:
        value: A scalar drawn from a polars Series.

    Returns:
        A JSON scalar. Temporal values become ISO 8601 strings, floats are
        rounded to `FLOAT_ROUND_DP`, and non-finite floats become their repr so
        the document stays valid JSON rather than emitting a bare `NaN`.
    """
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return repr(value) if not math.isfinite(value) else round(value, FLOAT_ROUND_DP)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    return str(value)


def _sort_key(value: JsonScalar) -> tuple[int, float, str]:
    """Total, type-safe ordering key for histogram tie-breaks.

    Args:
        value: An already-normalised JSON scalar.

    Returns:
        A tuple that orders any two scalars deterministically, so equal counts
        always break the same way across runs.
    """
    if value is None:
        return (0, 0.0, "")
    if isinstance(value, bool):
        return (1, float(value), "")
    if isinstance(value, int | float):
        return (2, float(value), "")
    return (3, 0.0, value)


def _blank_count(series: pl.Series) -> int:
    """Count empty or whitespace-only strings.

    Args:
        series: The column to inspect.

    Returns:
        The number of blank strings, or 0 for a non-string column. Nulls are not
        blanks — they are counted separately — so the two never double-count.
    """
    if series.dtype != pl.String:
        return 0
    return int(series.str.strip_chars().eq("").fill_null(value=False).sum())


def _top_values(series: pl.Series) -> list[JsonValue]:
    """Build a full value histogram over the non-null values of a column.

    Args:
        series: The column to count.

    Returns:
        `{"value": …, "count": …}` entries sorted by count descending then value
        ascending. Nulls are excluded — `null_count` already reports them.
    """
    frame = series.drop_nulls().value_counts(sort=False)
    value_column, count_column = frame.columns
    pairs: list[tuple[JsonScalar, int]] = [
        (_json_scalar(value), int(count))
        for value, count in zip(
            frame[value_column].to_list(), frame[count_column].to_list(), strict=True
        )
    ]
    pairs.sort(key=lambda pair: (-pair[1], _sort_key(pair[0])))
    entries: list[JsonValue] = [{"value": value, "count": count} for value, count in pairs]
    return entries


def _value_suppression(name: str, dtype: pl.DataType, distinct_count: int) -> str | None:
    """Decide whether a column's individual values may be committed.

    Two independent controls, applied in order:

    1. **PDPA disclosure.** Where `grid.pr001.columns.is_restricted` is true the
       column is personal data, free text with embedded personal data, or a
       quarantined credential/infrastructure payload. Without this
       `GL_ELIGIBILITY_APPROVE_BY` would land 24 real staff user IDs in the
       committed fixture and `DOCTOR_NAME` would land two real doctors' names.
       Unknown columns are caught here too, because `is_restricted` fails closed.
    2. **Real clinic data (CLAUDE.md guardrail 5).** An unbounded string column
       holds provider records — trading names, address lines, city names, GUIDs,
       provider codes — and its lexicographic bounds are themselves real provider
       strings. A string column earns its values back only by being a bounded code
       vocabulary (`STATUS_CODE`, `STATE_CODE`, `PROVIDER_TYPE_CODE` and friends),
       which is precisely what lets the drift detector catch a new code appearing.

    Numeric and temporal columns are never suppressed by control 2: their bounds
    are the drift signals that matter most and they carry no identity.

    Args:
        name: Column name.
        dtype: The polars dtype as reported for the column.
        distinct_count: Non-null distinct values in the column.

    Returns:
        The `values_suppressed` marker, or None when values may be emitted.
    """
    if is_restricted(name):
        return SUPPRESSION_PDPA
    if dtype == pl.String and distinct_count > TOP_VALUES_MAX_DISTINCT:
        return SUPPRESSION_FREE_TEXT
    return None


def _profile_column(name: str, series: pl.Series, row_count: int) -> dict[str, JsonValue]:
    """Profile a single column.

    Args:
        name: Column name.
        series: The column's values.
        row_count: Total rows in the file, used to derive `real_count`.

    Returns:
        The column's profile entry. Counts are always present. A suppressed
        column carries a `values_suppressed` marker and omits `min`, `max` and
        `top_values` entirely — see `_value_suppression`.
    """
    dtype = series.dtype
    null_count = int(series.null_count())
    blank_count = _blank_count(series)
    # Polars counts NULL as one distinct value; the profile reports non-null distincts.
    distinct_count = int(series.n_unique()) - (1 if null_count else 0)

    profile: dict[str, JsonValue] = {
        "name": name,
        "parquet_type": str(dtype),
        "logical_type": _logical_type(name, dtype),
        "null_count": null_count,
        "blank_count": blank_count,
        "real_count": row_count - null_count - blank_count,
        "distinct_count": distinct_count,
    }

    suppression = _value_suppression(name, dtype, distinct_count)
    if suppression is not None:
        profile["values_suppressed"] = suppression
        return profile

    if _is_ordered(dtype):
        profile["min"] = _json_scalar(series.min())
        profile["max"] = _json_scalar(series.max())
    if distinct_count <= TOP_VALUES_MAX_DISTINCT:
        profile["top_values"] = _top_values(series)
    return profile


def profile_parquet(path: Path) -> dict[str, JsonValue]:
    """Profile every column of a parquet file.

    Args:
        path: Path to the parquet file.

    Returns:
        A JSON-ready profile: `profile_schema_version`, `source_filename`
        (basename only — absolute paths would break reproducibility across
        machines), `source_sha256`, `row_count`, `column_count` and the `columns`
        list in physical file order.

    Raises:
        FileNotFoundError: If `path` is not an existing file. A missing source is
            a failure, never an empty success.
    """
    if not path.is_file():
        raise FileNotFoundError(f"parquet file not found: {path}")

    frame = pl.read_parquet(path)
    row_count = frame.height
    columns: list[JsonValue] = [
        _profile_column(name, frame[name], row_count) for name in frame.columns
    ]
    return {
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "source_filename": path.name,
        "source_sha256": _sha256(path),
        "row_count": row_count,
        "column_count": frame.width,
        "columns": columns,
    }


def render_json(profile: Mapping[str, JsonValue]) -> str:
    """Render a profile as canonical JSON text.

    Args:
        profile: A profile as returned by `profile_parquet`.

    Returns:
        Sorted-key, 2-space-indented, ASCII-only JSON with a trailing newline.
        Callers must write it with `newline="\\n"` to keep the bytes stable on
        Windows.
    """
    return json.dumps(profile, sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def write_profile(profile: Mapping[str, JsonValue], out: Path) -> None:
    """Write a profile to disk with fixed `\\n` line endings.

    Args:
        profile: A profile as returned by `profile_parquet`.
        out: Destination path; parent directories are created.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_json(profile), encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Argument vector; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code — 0 on success, 2 when the parquet file is missing.
    """
    parser = argparse.ArgumentParser(
        prog="profile_parquet",
        description="Emit a deterministic JSON profile of a parquet file.",
    )
    parser.add_argument("parquet", type=Path, help="Parquet file to profile.")
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=None,
        help="Write the profile here. Omit to write it to stdout.",
    )
    args = parser.parse_args(argv)

    try:
        profile = profile_parquet(args.parquet)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.out is None:
        # Bypass the text layer: Windows would otherwise translate \n to \r\n.
        sys.stdout.buffer.write(render_json(profile).encode("utf-8"))
    else:
        write_profile(profile, args.out)
        print(f"wrote profile to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
