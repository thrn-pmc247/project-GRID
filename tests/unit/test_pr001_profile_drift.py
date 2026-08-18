"""Drift tests for the committed PR001 profile fixture.

Tests with deliberately different reach:

* The `test_fixture_*` and `test_*_columns*` tests check the committed fixture
  against the column contract without touching the extract, so they run
  everywhere including CI, which never has `PR001.parquet` (gitignored —
  CLAUDE.md guardrail 5). Between them they assert both suppression controls:
  the PDPA one (`values_suppressed: "pdpa"`, personal data must not be
  disclosed) and the guardrail-5 one (`values_suppressed: "free_text"`, real
  clinic data must not be committed).
* `test_profile_matches_fixture` re-profiles the real extract when a developer
  machine has it and fails with a per-column diff naming exactly what moved.
  The profiler is imported lazily so that a missing polars can never stop the
  fixture-only tests above from being collected.

Source shrinkage — fewer rows, or any column losing real values — is reported as
its own clearly-labelled failure ahead of the ordinary diff. A source quietly
losing fill is the failure mode this file exists to catch.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

from grid.pr001.columns import EXPECTED_ROW_COUNT, SOURCE_COLUMNS, is_restricted

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
PARQUET_PATH: Final = REPO_ROOT / "PR001.parquet"
FIXTURE_PATH: Final = REPO_ROOT / "tests" / "fixtures" / "pr001_profile.json"
TOOLS_DIR: Final = REPO_ROOT / "tools"

EXPECTED_SCHEMA_VERSION: Final = 1
"""Mirrors `tools/profile_parquet.PROFILE_SCHEMA_VERSION`, restated rather than imported
so this test keeps running where polars is absent."""

SUPPRESSED_KEYS: Final = ("min", "max", "top_values")
"""Keys a suppressed column must never carry."""

SUPPRESSION_PDPA: Final = "pdpa"
SUPPRESSION_FREE_TEXT: Final = "free_text"

BOUNDED_VOCABULARY_MAX_DISTINCT: Final = 25
"""Mirrors `tools/profile_parquet.TOP_VALUES_MAX_DISTINCT`. At or below this many distinct
values a string column is a code vocabulary rather than a store of provider records."""

STRING_TYPE: Final = "String"
BOOLEAN_TYPE: Final = "Boolean"

BOUNDED_CODE_COLUMNS: Final = (
    "PROVIDER_TYPE_CODE",
    "CATEGORY_CODE",
    "STATE_CODE",
    "STATUS_CODE",
    "PAYMENT_METHOD_CODE",
    "OWNERSHIP_CODE",
    "id_LK180",
)
"""Code vocabularies that must keep their values — a new code appearing in any of these is
exactly the drift the fixture exists to catch."""

PROVIDER_IDENTIFYING_COLUMNS: Final = (
    "PROVIDER_CODE",
    "PROVIDER_DESCRIPTION",
    "ADDRESS1",
    "CITY",
    "POSTCODE",
    "ROW_GUID",
    "GST_COMPANY_NAME",
)
"""Unbounded strings whose bounds would be real provider records. Anchors the guardrail-5
control against a regression that silently re-admits them."""

TOP_LEVEL_FIELDS: Final = (
    "profile_schema_version",
    "source_filename",
    "source_sha256",
    "row_count",
    "column_count",
)

MAX_DIFF_LINES: Final = 60
"""Cap on reported diff lines, so a wholesale change stays readable."""

_ABSENT: Final[object] = object()
"""Sentinel for a field present on one side of a diff only."""


def _load_fixture() -> dict[str, Any]:
    """Read and parse the committed profile fixture.

    Returns:
        The parsed fixture.
    """
    if not FIXTURE_PATH.is_file():
        pytest.fail(
            f"the profile fixture is missing: {FIXTURE_PATH}\n"
            "It is committed deliberately — regenerate it with:\n"
            "  python tools/profile_parquet.py PR001.parquet -o tests/fixtures/pr001_profile.json"
        )
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _load_profiler() -> ModuleType:
    """Import `tools/profile_parquet.py` lazily.

    `tools/` is not a package and the profiler imports polars, so this must not
    run at collection time or CI would fail to collect the module at all.

    Returns:
        The imported profiler module.
    """
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    return importlib.import_module("profile_parquet")


def _columns_by_name(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index a profile's column entries by column name.

    Args:
        profile: A parsed profile.

    Returns:
        Column name to column entry.
    """
    return {column["name"]: column for column in profile["columns"]}


def _render(value: object) -> str:
    """Render a diff operand compactly.

    Args:
        value: The value, or `_ABSENT`.

    Returns:
        A short JSON rendering, truncated so a long histogram cannot flood the
        failure message.
    """
    if value is _ABSENT:
        return "<absent>"
    text = json.dumps(value, sort_keys=True)
    return text if len(text) <= 120 else f"{text[:117]}..."


def _format_failure(headline: str, lines: list[str]) -> str:
    """Assemble a readable multi-line failure message.

    Args:
        headline: One-line summary.
        lines: Detail lines.

    Returns:
        The formatted message, capped at `MAX_DIFF_LINES` detail lines.
    """
    shown = lines[:MAX_DIFF_LINES]
    if len(lines) > MAX_DIFF_LINES:
        shown.append(f"... and {len(lines) - MAX_DIFF_LINES} further difference(s)")
    return "\n".join([headline, *shown])


def _shrinkage_report(committed: dict[str, Any], fresh: dict[str, Any]) -> list[str]:
    """Find losses of data between the committed profile and a fresh one.

    Args:
        committed: The fixture profile.
        fresh: The freshly computed profile.

    Returns:
        One line per loss: fewer rows, a column gone, or a column with fewer real
        values than before. Empty when nothing shrank.
    """
    losses: list[str] = []
    old_rows, new_rows = committed["row_count"], fresh["row_count"]
    if new_rows < old_rows:
        losses.append(f"row_count fell by {old_rows - new_rows}: {old_rows} -> {new_rows}")

    old_columns = _columns_by_name(committed)
    new_columns = _columns_by_name(fresh)
    for name in (c["name"] for c in committed["columns"]):
        current = new_columns.get(name)
        if current is None:
            losses.append(f"{name}: column disappeared from the source")
            continue
        before, after = old_columns[name]["real_count"], current["real_count"]
        if after < before:
            losses.append(f"{name}.real_count fell by {before - after}: {before} -> {after}")
    return losses


def _column_diff(name: str, previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Diff one column entry field by field.

    Args:
        name: Column name.
        previous: The fixture's entry.
        current: The freshly computed entry.

    Returns:
        One line per changed field.
    """
    lines: list[str] = []
    for field in sorted(previous.keys() | current.keys()):
        if field == "name":
            continue
        before = previous.get(field, _ABSENT)
        after = current.get(field, _ABSENT)
        if before != after:
            lines.append(f"  {name}.{field}: {_render(before)} -> {_render(after)}")
    return lines


def _diff_report(committed: dict[str, Any], fresh: dict[str, Any]) -> list[str]:
    """Diff a fresh profile against the committed one.

    Args:
        committed: The fixture profile.
        fresh: The freshly computed profile.

    Returns:
        One line per difference, in file order. Empty when the two match.
    """
    lines: list[str] = []
    for field in TOP_LEVEL_FIELDS:
        before, after = committed.get(field, _ABSENT), fresh.get(field, _ABSENT)
        if before != after:
            lines.append(f"  {field}: {_render(before)} -> {_render(after)}")

    old_columns = _columns_by_name(committed)
    new_columns = _columns_by_name(fresh)
    for name in sorted(old_columns.keys() - new_columns.keys()):
        lines.append(f"  {name}: column removed")
    for name in sorted(new_columns.keys() - old_columns.keys()):
        lines.append(f"  {name}: column added")
    for name in (c["name"] for c in committed["columns"]):
        if name in new_columns:
            lines.extend(_column_diff(name, old_columns[name], new_columns[name]))
    return lines


def test_fixture_is_well_formed() -> None:
    """The committed fixture parses and matches the PR001 column contract.

    Runs in CI, where the extract itself is absent.
    """
    profile = _load_fixture()

    assert profile["profile_schema_version"] == EXPECTED_SCHEMA_VERSION
    assert profile["source_filename"] == "PR001.parquet", "must be a basename, never a path"
    assert profile["row_count"] == EXPECTED_ROW_COUNT
    assert profile["column_count"] == len(SOURCE_COLUMNS) == 70

    columns = profile["columns"]
    assert len(columns) == 70
    assert tuple(column["name"] for column in columns) == SOURCE_COLUMNS, (
        "column order must match the physical file order recorded in the contract"
    )

    for column in columns:
        name = column["name"]
        counted = column["null_count"] + column["blank_count"] + column["real_count"]
        assert counted == profile["row_count"], (
            f"{name}: null + blank + real = {counted}, expected {profile['row_count']}"
        )
        assert column["distinct_count"] >= 0
        assert column["logical_type"] and not column["logical_type"].startswith("UNMAPPED")


def test_fixture_suppresses_restricted_columns() -> None:
    """No restricted column leaks values into the committed fixture.

    CLAUDE.md guardrail 5 and `docs/context/compliance-pdpa.md`: personal data,
    free text with embedded personal data and quarantined credential or
    infrastructure payloads never reach a committed artefact. Counts are
    aggregates and are fine; `min`, `max` and `top_values` are not.
    """
    profile = _load_fixture()
    leaks: list[str] = []
    mislabelled: list[str] = []

    for column in profile["columns"]:
        name = column["name"]
        present = [key for key in SUPPRESSED_KEYS if key in column]
        marker = column.get("values_suppressed")
        if is_restricted(name):
            if marker != SUPPRESSION_PDPA:
                mislabelled.append(
                    f"  {name}: restricted, so values_suppressed must be "
                    f"'{SUPPRESSION_PDPA}', found {marker!r}"
                )
            if present:
                leaks.append(f"  {name}: restricted but carries {', '.join(present)}")
        elif marker == SUPPRESSION_PDPA:
            mislabelled.append(f"  {name}: marked '{SUPPRESSION_PDPA}' but is not restricted")

    assert not leaks, _format_failure("PDPA LEAK — restricted columns expose values:", leaks)
    assert not mislabelled, _format_failure("Suppression markers are inconsistent:", mislabelled)


def test_fixture_commits_no_free_text_provider_values() -> None:
    """No unbounded string column commits real provider values.

    CLAUDE.md guardrail 5 — never commit real clinic data — is a separate control
    from PDPA disclosure. A string column's lexicographic bounds are themselves
    real provider records: `PROVIDER_DESCRIPTION`'s max is a clinic's trading
    name and `ADDRESS1`'s is a real address, neither of which is personal data
    but both of which are real clinic data. Only a bounded code vocabulary earns
    its values back.

    Asserted in both directions, so neither over- nor under-suppression passes.
    """
    profile = _load_fixture()
    problems: list[str] = []

    for column in profile["columns"]:
        name = column["name"]
        if is_restricted(name):
            continue  # the PDPA control owns these; checked separately above
        distinct = column["distinct_count"]
        present = {key for key in SUPPRESSED_KEYS if key in column}
        marker = column.get("values_suppressed")
        bounded = distinct <= BOUNDED_VOCABULARY_MAX_DISTINCT

        if column["parquet_type"] == STRING_TYPE and not bounded:
            if marker != SUPPRESSION_FREE_TEXT:
                problems.append(
                    f"  {name}: unbounded string ({distinct} distinct) must be marked "
                    f"'{SUPPRESSION_FREE_TEXT}', found {marker!r}"
                )
            if present:
                problems.append(f"  {name}: unbounded string carries {', '.join(sorted(present))}")
            continue

        if marker is not None:
            problems.append(f"  {name}: suppressed as {marker!r} but its values are permitted")
            continue

        # Ordered types keep bounds; booleans convey the same through top_values.
        expected = set() if column["parquet_type"] == BOOLEAN_TYPE else {"min", "max"}
        if bounded:
            expected.add("top_values")
        missing = sorted(expected - present)
        if missing:
            problems.append(f"  {name}: should carry {', '.join(missing)} but does not")

    assert not problems, _format_failure(
        "Value-suppression rule violated (guardrail 5 — real clinic data):", problems
    )


def test_bounded_code_columns_keep_their_vocabulary() -> None:
    """The code columns the drift detector depends on still carry their values."""
    columns = _columns_by_name(_load_fixture())
    for name in BOUNDED_CODE_COLUMNS:
        column = columns[name]
        assert "values_suppressed" not in column, f"{name} must keep its code vocabulary"
        assert column["top_values"], f"{name} needs top_values to catch a new code appearing"
        assert "min" in column and "max" in column, f"{name} must keep its bounds"


def test_provider_identifying_columns_are_suppressed() -> None:
    """Columns whose values identify an individual provider commit no values."""
    columns = _columns_by_name(_load_fixture())
    for name in PROVIDER_IDENTIFYING_COLUMNS:
        column = columns[name]
        assert column.get("values_suppressed") == SUPPRESSION_FREE_TEXT, (
            f"{name} holds real provider records and must be suppressed as free_text"
        )
        leaked = [key for key in SUPPRESSED_KEYS if key in column]
        assert not leaked, f"{name} leaks {', '.join(leaked)}"


def test_profile_matches_fixture() -> None:
    """Re-profiling the real extract reproduces the committed fixture exactly.

    Skipped where the extract is unavailable — it is gitignored, so CI never has
    it and the fixture-only tests above carry the load there.
    """
    if not PARQUET_PATH.is_file():
        pytest.skip(f"{PARQUET_PATH.name} is absent (gitignored); fixture-only checks apply")
    pytest.importorskip("polars", reason="the profiler cannot run without polars")

    fresh = _load_profiler().profile_parquet(PARQUET_PATH)
    committed = _load_fixture()

    losses = _shrinkage_report(committed, fresh)
    assert not losses, _format_failure(
        "SOURCE SHRINKAGE — the extract lost data against the committed profile. "
        "Investigate the extract before regenerating the fixture:",
        losses,
    )

    differences = _diff_report(committed, fresh)
    assert not differences, _format_failure(
        "PR001 profile drift — the extract no longer matches the committed fixture. "
        "If the change is expected, regenerate with:\n"
        "  python tools/profile_parquet.py PR001.parquet -o tests/fixtures/pr001_profile.json",
        differences,
    )
