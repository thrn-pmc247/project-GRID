"""Contract tests for the PR001 column definitions.

`grid.pr001.columns` is the single source of truth every other layer reads its rules
from — the bronze loader's column-set assertion, staging's drop and quarantine
boundaries, the PDPA view audit and the generated data dictionary all defer to it. A
silent edit here would relax a control everywhere at once without any of those layers
noticing, so the shape of the contract is asserted directly.

The load-bearing test in this file is `test_is_restricted_fails_closed_on_unknown_column`.
Every other assertion here would fail loudly if the contract drifted; that one is the only
place where the *default* is checked, and a PDPA control whose default is "permit" is not
a control.
"""

from __future__ import annotations

from collections import Counter
from typing import Final

import pytest

from grid.pr001.columns import (
    ACC_VENDOR_FLAG_SENTINEL_YEAR,
    BRONZE_AUDIT_COLUMNS,
    DROPPED_AT_STAGING,
    EXPECTED_ROW_COUNT,
    PERSONAL_DATA_COLUMNS,
    QUARANTINED,
    RESTRICTED_COLUMNS,
    SOURCE_COLUMN_SPECS,
    SOURCE_COLUMNS,
    SPEC_BY_NAME,
    TIME_COLUMNS,
    TIMESTAMP_COLUMNS,
    USER_ID_COLUMNS,
    Confidence,
    Disposition,
    LogicalType,
    PdpaClass,
    is_restricted,
)

EXPECTED_COLUMN_COUNT: Final = 70

EXPECTED_DISPOSITION_COUNTS: Final[dict[Disposition, int]] = {
    Disposition.KEEP: 51,
    Disposition.DROP: 5,
    Disposition.QUARANTINE: 2,
    Disposition.PII: 12,
}
"""The brief's dispositions, corroborated by profiling (docs/reconciliation-pr001.md §7)."""

EXPECTED_RESTRICTED_COUNT: Final = 17
"""12 personal + 3 embedded-personal free text + 2 quarantined, less the one column that
is both personal and quarantined (`QR_ENCRYPTED_TEXT`)."""

UNKNOWN_COLUMN_NAMES: Final[tuple[str, ...]] = (
    "",
    "NOT_A_COLUMN",
    "doctor_name",  # the staging rename, not a source column name
    "PROVIDER_CODE_2",
    "DROP TABLE bronze.pr001_provider_master",
)
"""Names absent from the contract. Every one must be treated as restricted."""


def test_contract_holds_seventy_columns() -> None:
    """The contract declares exactly 70 columns and no name is repeated."""
    assert len(SOURCE_COLUMN_SPECS) == EXPECTED_COLUMN_COUNT
    assert len(SOURCE_COLUMNS) == EXPECTED_COLUMN_COUNT
    duplicates = [name for name, count in Counter(SOURCE_COLUMNS).items() if count > 1]
    assert not duplicates, f"column names must be unique; repeated: {duplicates}"
    assert len(SPEC_BY_NAME) == EXPECTED_COLUMN_COUNT


def test_source_columns_order_matches_the_specs() -> None:
    """`SOURCE_COLUMNS` is the spec order verbatim.

    Bronze records `_row_ordinal` against physical file order and asserts the column set
    on load, so a reordering here would silently invalidate every prior generation's
    ordinals.
    """
    spec_order = tuple(spec.name for spec in SOURCE_COLUMN_SPECS)
    assert spec_order == SOURCE_COLUMNS


@pytest.mark.parametrize(
    ("disposition", "expected"),
    list(EXPECTED_DISPOSITION_COUNTS.items()),
    ids=[disposition.value for disposition in EXPECTED_DISPOSITION_COUNTS],
)
def test_disposition_buckets_are_the_expected_size(disposition: Disposition, expected: int) -> None:
    """Each disposition bucket holds the number of columns the brief states."""
    actual = sum(1 for spec in SOURCE_COLUMN_SPECS if spec.disposition is disposition)
    assert actual == expected


def test_dispositions_partition_the_contract() -> None:
    """Every column has exactly one disposition and the buckets sum to 70."""
    assert sum(EXPECTED_DISPOSITION_COUNTS.values()) == EXPECTED_COLUMN_COUNT
    counted = Counter(spec.disposition for spec in SOURCE_COLUMN_SPECS)
    assert dict(counted) == EXPECTED_DISPOSITION_COUNTS


def test_derived_column_tuples_agree_with_the_specs() -> None:
    """The convenience tuples are derivations, not a second hand-maintained list."""
    dropped = tuple(
        spec.name for spec in SOURCE_COLUMN_SPECS if spec.disposition is Disposition.DROP
    )
    personal = tuple(
        spec.name for spec in SOURCE_COLUMN_SPECS if spec.pdpa_class is PdpaClass.PERSONAL
    )
    timestamps = tuple(
        spec.name
        for spec in SOURCE_COLUMN_SPECS
        if spec.logical_type is LogicalType.TIMESTAMP_MICROS
    )
    times = tuple(
        spec.name for spec in SOURCE_COLUMN_SPECS if spec.logical_type is LogicalType.TIME_NANOS
    )

    assert dropped == DROPPED_AT_STAGING
    assert personal == PERSONAL_DATA_COLUMNS
    assert timestamps == TIMESTAMP_COLUMNS
    assert times == TIME_COLUMNS
    assert QUARANTINED == ("QR_ENCRYPTED_TEXT", "QR_FILE_PATH")


def test_restricted_columns_has_seventeen_members() -> None:
    """17 columns are barred from shareable views, fixtures and logs."""
    restricted = frozenset(spec.name for spec in SOURCE_COLUMN_SPECS if spec.restricted)

    assert len(RESTRICTED_COLUMNS) == EXPECTED_RESTRICTED_COUNT
    assert restricted == RESTRICTED_COLUMNS


def test_restricted_covers_personal_embedded_and_quarantined() -> None:
    """Restriction is the union of the three grounds, and nothing else.

    Asserted in both directions: a business-classed, non-quarantined column must not be
    restricted either, or the control would be meaninglessly broad.
    """
    for spec in SOURCE_COLUMN_SPECS:
        grounds = (
            spec.pdpa_class is PdpaClass.PERSONAL,
            spec.pdpa_class is PdpaClass.BUSINESS_EMBEDDED_PERSONAL,
            spec.disposition is Disposition.QUARANTINE,
        )
        assert spec.restricted is any(grounds), f"{spec.name}: restriction is inconsistent"

    assert set(PERSONAL_DATA_COLUMNS) <= RESTRICTED_COLUMNS
    assert set(QUARANTINED) <= RESTRICTED_COLUMNS
    assert "PROVIDER_CODE" not in RESTRICTED_COLUMNS
    assert "POSTCODE" not in RESTRICTED_COLUMNS


@pytest.mark.parametrize("column", UNKNOWN_COLUMN_NAMES)
def test_is_restricted_fails_closed_on_unknown_column(column: str) -> None:
    """An unrecognised column name is restricted.

    This is the one that matters. `is_restricted` gates disclosure, so its behaviour on
    an input it does not recognise decides what happens when a column is renamed
    upstream, misspelled in a view definition, or added to the source without the
    contract being updated. Failing closed is the only safe default for a PDPA control:
    a name we cannot classify must be withheld, never permitted.
    """
    assert is_restricted(column) is True


def test_is_restricted_agrees_with_the_specs_for_known_columns() -> None:
    """Failing closed must not degrade into "everything is restricted"."""
    for spec in SOURCE_COLUMN_SPECS:
        assert is_restricted(spec.name) is spec.restricted
    assert any(not is_restricted(name) for name in SOURCE_COLUMNS), (
        "if no known column were permitted the control would be vacuous"
    )


def test_embedded_personal_columns_are_the_documented_three() -> None:
    """`WEBSITE`, `REMARKS` and `SYS_ADMIN_REMARKS` are the documented deviations.

    All three are nominally business free text that demonstrably carries staff names, so
    they stay usable inside the pipeline (the REMARKS miner needs them) but are excluded
    from shareable views. The set is asserted so a fourth cannot be added without a
    deliberate decision.
    """
    embedded = tuple(
        spec.name
        for spec in SOURCE_COLUMN_SPECS
        if spec.pdpa_class is PdpaClass.BUSINESS_EMBEDDED_PERSONAL
    )
    assert embedded == ("WEBSITE", "REMARKS", "SYS_ADMIN_REMARKS")


def test_unknown_confidence_columns_declare_a_note() -> None:
    """A column we do not understand says so, rather than carrying a plausible guess.

    Guardrail 10: flag uncertainty instead of inventing meaning.
    """
    undocumented = [
        spec.name
        for spec in SOURCE_COLUMN_SPECS
        if spec.confidence is Confidence.UNKNOWN and not spec.definition
    ]
    assert not undocumented, f"unknown-confidence columns need a definition: {undocumented}"


def test_audit_and_sentinel_constants() -> None:
    """The audit column names and the sentinel year are stable.

    Bronze's five audit columns are underscore-prefixed precisely so they cannot collide
    with a source column, and the sentinel year is what staging remaps to NULL.
    """
    assert BRONZE_AUDIT_COLUMNS == (
        "_ingest_id",
        "_ingested_at",
        "_source_filename",
        "_source_sha256",
        "_row_ordinal",
    )
    assert not set(BRONZE_AUDIT_COLUMNS) & set(SOURCE_COLUMNS)
    assert all(name.startswith("_") for name in BRONZE_AUDIT_COLUMNS)
    assert ACC_VENDOR_FLAG_SENTINEL_YEAR == 1900
    assert EXPECTED_ROW_COUNT == 33_643


def test_user_id_columns_are_all_personal_data() -> None:
    """The four staff user-ID columns are personal data and case-folded into ref_user."""
    assert USER_ID_COLUMNS == (
        "GL_ELIGIBILITY_APPROVE_BY",
        "STATUS_BY",
        "CREATE_BY",
        "MODIFY_BY",
    )
    for name in USER_ID_COLUMNS:
        spec = SPEC_BY_NAME[name]
        assert spec.pdpa_class is PdpaClass.PERSONAL, f"{name} must be personal data"
        assert spec.disposition is Disposition.PII, f"{name} must be segregated into pii"
