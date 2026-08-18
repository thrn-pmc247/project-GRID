"""Generate the machine-readable PR001 data dictionary.

Reads the column contract in :mod:`grid.pr001.columns` — the single source of truth for
all 70 PR001 source columns — and writes ``docs/data-dictionary-pr001.yaml``.

The dictionary is **generated, never hand-edited**: a hand-maintained copy would drift
from the contract the loader actually enforces, and the drift would be silent.

Two properties this module guarantees:

* **Deterministic.** Same contract plus same profile in, byte-identical file out. No
  generation timestamp is emitted, precisely so that a re-run produces no diff.
* **Disclosure-safe.** The dictionary carries names, logical types, counts and
  definitions only. Illustrative *values* quoted in the contract's notes — staff names,
  an internal server address, sample provider and company registration numbers — are
  redacted by :data:`REDACTIONS` and their absence is then asserted against the rendered
  text. The generator fails loudly rather than emitting a value it was asked to suppress.

Fill rates come from ``tests/fixtures/pr001_profile.json`` when that fixture exists. When
it does not, every ``fill_rate`` is ``null`` and ``fill_rate_source`` says so. Fill rates
are never invented (guardrail 10).

Usage::

    python tools/generate_data_dictionary.py [--check]

``--check`` regenerates in memory and exits non-zero if the file on disk differs, for
use in CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import yaml

from grid.pr001.columns import (
    EXPECTED_ROW_COUNT,
    SOURCE_COLUMN_SPECS,
    ColumnSpec,
    Confidence,
    Disposition,
)

REPO: Final = Path(__file__).resolve().parents[1]
OUTPUT_PATH: Final = REPO / "docs" / "data-dictionary-pr001.yaml"
PROFILE_PATH: Final = REPO / "tests" / "fixtures" / "pr001_profile.json"

GENERATOR: Final = "tools/generate_data_dictionary.py"
CONTRACT_MODULE: Final = "src/grid/pr001/columns.py"
SOURCE_FILE: Final = "PR001.parquet"
EXTRACT_VINTAGE: Final = "2026-08-05"
"""Max ``SYS_TIME_STAMP`` in the profiled extract (docs/reconciliation-pr001.md §7)."""

FILL_RATE_UNAVAILABLE: Final = (
    "unavailable — regenerate after tests/fixtures/pr001_profile.json exists"
)
DROP_PREFIX: Final = "Dropped at staging: "

REDACTIONS: Final[tuple[tuple[str, str], ...]] = (
    # Staff identities quoted as examples in the contract notes.
    ("(M_NOOR == m_noor)", "(case variants of one user ID fold to one person)"),
    (
        "populated values include staff names ('MS. YAP', 'JAYANTHI')",
        "populated values include individual staff names",
    ),
    (
        "they routinely name PMCare staff ('EMAIL AFIQ', 'AFIQAH 12022026')",
        "they routinely name PMCare staff",
    ),
    # Internal infrastructure disclosure.
    (
        "contains an internal server address (\\\\10.51.51.99\\LineDoc\\...)",
        "contains an internal file-server UNC path",
    ),
    # Sample identifiers belonging to real providers and companies.
    (
        "Not numeric — ranges over GOH, 0101252, DEN4022, PH036; lengths 5-12.",
        "Not numeric — alphabetic, numeric and prefixed forms occur; lengths 5-12.",
    ),
    (
        "Invalids include 814000, 8480, 'CV5 6J' (UK) and encoding corruption.",
        "Invalids include six- and four-digit values, one UK-format postcode and "
        "encoding corruption.",
    ),
    (
        "genuine SSM numbers (202501030274), old-format (591650-X), "
        "and a company NAME ('JKLE SDN BHD')",
        "genuine 12-digit SSM numbers, old-format hyphenated ones, and at least one company NAME",
    ),
)
"""Exact substring substitutions applied to every definition and note.

Explicit rather than pattern-based so the suppression is auditable and deterministic.
If the contract's wording changes, the substitution silently stops matching — which is
why :data:`FORBIDDEN_LITERALS` is asserted separately against the rendered document.
"""

FORBIDDEN_LITERALS: Final[frozenset[str]] = frozenset(
    {
        "M_NOOR",
        "MS. YAP",
        "JAYANTHI",
        "EMAIL AFIQ",
        "AFIQAH",
        "10.51.51.99",
        "LineDoc",
        "DEN4022",
        "0101252",
        "PH036",
        "CV5 6J",
        "202501030274",
        "591650-X",
        "JKLE SDN BHD",
    }
)
"""Values that must never reach the published dictionary. Checked post-render."""

_REAL_COUNT_KEYS: Final = (
    "real",
    "real_count",
    "real_values",
    "non_blank",
    "non_blank_count",
    "populated",
    "populated_count",
)
_NULL_COUNT_KEYS: Final = ("null_count", "nulls", "null")
_BLANK_COUNT_KEYS: Final = ("blank_count", "blanks", "blank")
_ROW_COUNT_KEYS: Final = ("row_count", "rows", "n_rows", "num_rows")


def redact(text: str) -> str:
    """Apply :data:`REDACTIONS` to one definition or note.

    Args:
        text: Contract prose, possibly quoting illustrative data values.

    Returns:
        The same prose with every known illustrative value replaced by a description
        of its shape.
    """
    for needle, replacement in REDACTIONS:
        text = text.replace(needle, replacement)
    return text


def _first_number(entry: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    """Return the first numeric value found under `keys`, or None."""
    for key in keys:
        value = entry.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return float(value)
    return None


def _column_entries(profile: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Normalise the profile's column section into a name-keyed mapping.

    Tolerates both shapes a profiler might emit: a mapping of column name to stats, or
    a list of stat objects each carrying its own ``name``/``column``.
    """
    raw = profile.get("columns", profile)
    entries: dict[str, Mapping[str, Any]] = {}
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if isinstance(key, str) and isinstance(value, Mapping):
                entries[key] = value
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name") or item.get("column") or item.get("column_name")
            if isinstance(name, str):
                entries[name] = item
    return entries


def load_profile() -> tuple[dict[str, Mapping[str, Any]], int, str | None]:
    """Load fill-rate inputs from the profile fixture if it exists.

    Returns:
        A triple of (column stats by name, row count, source description). The source
        description is None when no fixture is present, which is the caller's signal to
        emit null fill rates rather than guessing them.
    """
    if not PROFILE_PATH.is_file():
        return {}, EXPECTED_ROW_COUNT, None
    try:
        loaded = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}, EXPECTED_ROW_COUNT, None
    if not isinstance(loaded, Mapping):
        return {}, EXPECTED_ROW_COUNT, None
    entries = _column_entries(loaded)
    if not entries:
        return {}, EXPECTED_ROW_COUNT, None
    rows = _first_number(loaded, _ROW_COUNT_KEYS)
    row_count = int(rows) if rows else EXPECTED_ROW_COUNT
    return entries, row_count, "tests/fixtures/pr001_profile.json"


def fill_rate_for(entry: Mapping[str, Any] | None, row_count: int) -> float | None:
    """Derive a column's fill rate as a fraction of non-blank, non-null values.

    Blank strings are counted as empty, not as data: PR001 uses the blank string as its
    real "empty" in several columns, and treating blanks as filled would overstate every
    fill rate in the project (docs/reconciliation-pr001.md §3).

    Args:
        entry: That column's stats from the profile fixture, or None.
        row_count: Total rows in the extract.

    Returns:
        A fraction in [0, 1] rounded to four places, or None when the profile cannot
        support the calculation.
    """
    if entry is None or row_count <= 0:
        return None
    direct = _first_number(entry, ("fill_rate", "fill_ratio"))
    if direct is not None:
        rate = direct / 100.0 if direct > 1.0 else direct
        return round(rate, 4)
    real = _first_number(entry, _REAL_COUNT_KEYS)
    if real is None:
        nulls = _first_number(entry, _NULL_COUNT_KEYS)
        blanks = _first_number(entry, _BLANK_COUNT_KEYS)
        if nulls is None:
            return None
        real = row_count - nulls - (blanks or 0.0)
    return round(max(0.0, min(float(real), float(row_count))) / row_count, 4)


def column_document(
    spec: ColumnSpec,
    entry: Mapping[str, Any] | None,
    row_count: int,
    profile_source: str | None,
) -> dict[str, Any]:
    """Build the YAML mapping for one column, in the contract's field order."""
    rate = fill_rate_for(entry, row_count) if profile_source else None
    document: dict[str, Any] = {
        "name": spec.name,
        "type": spec.logical_type.value,
        "definition": redact(spec.definition),
        "fill_rate": rate,
        "fill_rate_source": (
            f"{profile_source} (non-blank, non-null / {row_count:,} rows)"
            if rate is not None
            else FILL_RATE_UNAVAILABLE
        ),
        "disposition": spec.disposition.value,
        "pdpa_class": spec.pdpa_class.value,
        "confidence": spec.confidence.value,
        "restricted": spec.restricted,
        "note": redact(spec.note) if spec.note else None,
    }
    if spec.disposition is Disposition.DROP and spec.note:
        reason = redact(spec.note)
        document["drop_reason"] = (
            reason[len(DROP_PREFIX) :] if reason.startswith(DROP_PREFIX) else reason
        )
    return document


def build_document() -> str:
    """Render the whole dictionary, header comment included.

    Returns:
        The complete file text, ending in a newline, with LF line endings.
    """
    entries, row_count, profile_source = load_profile()
    dispositions = Counter(spec.disposition.value for spec in SOURCE_COLUMN_SPECS)
    confidences = Counter(spec.confidence.value for spec in SOURCE_COLUMN_SPECS)

    payload: dict[str, Any] = {
        "dataset": "PR001 provider master",
        "description": (
            "Field-level dictionary for the PMCare incumbent provider master extract. "
            "Business metadata only — no clinic, practitioner or staff data values."
        ),
        "source_file": SOURCE_FILE,
        "extract_vintage": EXTRACT_VINTAGE,
        "row_count": row_count,
        "column_count": len(SOURCE_COLUMN_SPECS),
        "contract_module": CONTRACT_MODULE,
        "profile_fixture": "tests/fixtures/pr001_profile.json",
        "profile_available": profile_source is not None,
        "references": [
            "docs/reconciliation-pr001.md",
            "docs/decisions/0005-pr001-as-incumbent-spine.md",
            "docs/decisions/0006-offline-sqlite-schemas-for-layered-model.md",
            "docs/context/data-model.md",
        ],
        "disposition_totals": {
            value.value: dispositions.get(value.value, 0) for value in Disposition
        },
        "confidence_totals": {value.value: confidences.get(value.value, 0) for value in Confidence},
        "columns": [
            column_document(spec, entries.get(spec.name), row_count, profile_source)
            for spec in SOURCE_COLUMN_SPECS
        ],
    }

    body = yaml.safe_dump(
        payload,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=96,
    )
    header = (
        "# PR001 data dictionary — GENERATED FILE, DO NOT EDIT BY HAND.\n"
        f"# Generated by {GENERATOR} from {CONTRACT_MODULE}.\n"
        "# Regenerate after any change to the column contract; the output is\n"
        "# deterministic, so a clean tree means the dictionary is in step.\n"
        "# Contains business metadata only: names, logical types, counts, definitions.\n"
        "# No clinic, practitioner or staff data values (PDPA 2010 as amended 2024).\n"
    )
    return header + body


def assert_no_data_values(text: str) -> None:
    """Fail loudly if a suppressed data value survived into the rendered document.

    Args:
        text: The full rendered dictionary.

    Raises:
        ValueError: If any literal in :data:`FORBIDDEN_LITERALS` is present.
    """
    leaked = sorted(literal for literal in FORBIDDEN_LITERALS if literal in text)
    if leaked:
        raise ValueError(
            f"data dictionary would disclose {len(leaked)} suppressed value(s); "
            "update REDACTIONS to match the current column contract wording"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Write (or verify) ``docs/data-dictionary-pr001.yaml``.

    Args:
        argv: Command-line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        Process exit code — 0 on success, 1 when ``--check`` finds the file stale.
    """
    parser = argparse.ArgumentParser(description="Generate the PR001 data dictionary")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed file matches the contract; write nothing",
    )
    args = parser.parse_args(argv)

    text = build_document()
    assert_no_data_values(text)

    if args.check:
        current = (
            OUTPUT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
            if OUTPUT_PATH.is_file()
            else ""
        )
        if current != text:
            print(f"stale: {OUTPUT_PATH.relative_to(REPO).as_posix()} — regenerate it")
            return 1
        print(f"up to date: {OUTPUT_PATH.relative_to(REPO).as_posix()}")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(
        f"wrote {OUTPUT_PATH.relative_to(REPO).as_posix()} — "
        f"{len(SOURCE_COLUMN_SPECS)} columns, "
        f"fill rates {'from the profile fixture' if 'profile_available: true' in text else 'null'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
