"""Tests for the PR001 reference vocabularies and the unknown-code guard.

The guard is the point of this module. `reference.py` declares every code present in the
2026-08-05 extract rather than discovering codes at load time, because a vocabulary that
grows itself can never detect growth. A code no reference table declares must break the
build — a new provider type is a business change needing a human decision, not a NULL
flowing quietly into staging.

So the central test here injects an undeclared code and asserts the build breaks, with an
error message actionable enough to act on: the offending table, the code, and how many
rows carry it.

All data is synthetic (see `tests/conftest.py`); `PR001.parquet` is gitignored and absent
in CI.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from grid.db.models import pr001_provider_master
from grid.pr001.bronze import load_bronze
from grid.pr001.reference import (
    CONFIRMED_BY_PNM,
    INFERRED,
    REF_TABLES,
    UNKNOWN,
    RefTableModel,
    UnknownCodeError,
    assert_codes_known,
    backfill_row_counts,
    declared_codes,
    observed_codes,
    seed_reference_tables,
)

UNDECLARED_PROVIDER_TYPE: Final = "QQ"
"""A provider-type code no reference table declares. It cannot collide with a real one:
the extract's 21 codes are enumerated in `PROVIDER_TYPE_SEEDS`."""

INJECTED_ROW_ORDINAL: Final = 9_999
"""Beyond the synthetic fixture's ordinals, so an injected row cannot collide."""

EXPECTED_SEED_COUNTS: Final[dict[str, int]] = {
    "ref_provider_type": 21,
    "ref_state": 18,
    "ref_status": 4,
    "ref_category": 7,
    "ref_payment_method": 3,
    "ref_ownership": 4,
    "ref_lk180": 4,
}
"""Every code observed in the 2026-08-05 extract, per vocabulary."""

UNKNOWN_MEANING_CODES: Final[tuple[tuple[str, str], ...]] = (
    ("ref_status", "V"),
    ("ref_state", "ZZ"),
    ("ref_state", "00"),
)
"""Individually unknown codes inside otherwise-evidenced vocabularies. `V` has 3 rows and
no corroborating date column; `ZZ` and `00` are not Malaysian states."""

WHOLLY_UNKNOWN_TABLES: Final[tuple[str, ...]] = (
    "ref_category",
    "ref_payment_method",
    "ref_ownership",
    "ref_lk180",
)
"""Vocabularies where not one code has an evidenced meaning."""

VALID_SOURCE_VALUES: Final[frozenset[str]] = frozenset({CONFIRMED_BY_PNM, INFERRED, UNKNOWN})

_MODEL_BY_LABEL: Final[dict[str, type[RefTableModel]]] = {
    spec.label: spec.model for spec in REF_TABLES
}


@pytest.fixture
def seeded_bronze(engine: Engine, synthetic_parquet: Path, synthetic_calibration: None) -> str:
    """Seed the vocabularies and land the synthetic extract in bronze.

    Returns:
        The bronze generation id.
    """
    seed_reference_tables(engine)
    return load_bronze(engine, synthetic_parquet).ingest_id


def _inject_row(
    engine: Engine, ingest_id: str, ordinal: int = INJECTED_ROW_ORDINAL, **values: object
) -> None:
    """Append one raw row to a bronze generation.

    Bronze accepts whatever the source holds — every source column is nullable — so a
    partial row is a legitimate insert. Used to plant a code the vocabularies do not
    declare.

    Args:
        engine: The engine holding the generation.
        ingest_id: Generation to append to.
        ordinal: `_row_ordinal` for the planted row; part of bronze's primary key.
        **values: Source column values for the planted row.
    """
    with engine.begin() as conn:
        conn.execute(
            pr001_provider_master.insert(),
            {
                "_ingest_id": ingest_id,
                "_row_ordinal": ordinal,
                "_ingested_at": dt.datetime(2026, 8, 17, 9, 0, 0),
                "_source_filename": "injected-by-test",
                "_source_sha256": "0" * 64,
                **values,
            },
        )


# --------------------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------------------


def test_seeding_writes_every_declared_code(engine: Engine) -> None:
    """Each vocabulary is seeded with exactly the codes the extract evidences."""
    written = seed_reference_tables(engine)
    assert written == EXPECTED_SEED_COUNTS

    with engine.connect() as conn:
        for spec in REF_TABLES:
            count = conn.execute(select(func.count()).select_from(spec.model)).scalar_one()
            assert count == EXPECTED_SEED_COUNTS[spec.label], spec.label


def test_seeding_is_idempotent(engine: Engine) -> None:
    """A second seed writes nothing and disturbs nothing.

    The seeder runs on every pipeline invocation, so re-running it must never duplicate a
    code nor overwrite a meaning a human has since confirmed.
    """
    first = seed_reference_tables(engine)
    second = seed_reference_tables(engine)

    assert first == EXPECTED_SEED_COUNTS
    assert second == dict.fromkeys(EXPECTED_SEED_COUNTS, 0), (
        "the second run must write no rows at all"
    )

    with engine.connect() as conn:
        for spec in REF_TABLES:
            count = conn.execute(select(func.count()).select_from(spec.model)).scalar_one()
            assert count == EXPECTED_SEED_COUNTS[spec.label], spec.label


def test_seeded_source_values_are_from_the_closed_set(engine: Engine) -> None:
    """`source` is always one of confirmed_by_pnm / inferred / unknown."""
    seed_reference_tables(engine)
    with Session(engine) as session:
        for spec in REF_TABLES:
            for row in session.execute(select(spec.model)).scalars():
                assert row.source in VALID_SOURCE_VALUES, f"{spec.label}.{row.code}"


@pytest.mark.parametrize(("label", "code"), UNKNOWN_MEANING_CODES)
def test_unknown_codes_carry_a_null_meaning(engine: Engine, label: str, code: str) -> None:
    """A code we do not understand records that, rather than a plausible guess.

    Guardrail 10 forbids inventing meanings. A NULL with a documented reason in `notes` is
    worth more than a confident-sounding invention, so both halves are asserted: the
    meaning must be NULL *and* the source must say `unknown`.
    """
    seed_reference_tables(engine)
    model = _MODEL_BY_LABEL[label]
    with Session(engine) as session:
        row = session.get(model, code)
        assert row is not None, f"{label} does not declare {code!r}"
        assert row.meaning is None, f"{label}.{code} must not claim a meaning"
        assert row.source == UNKNOWN
        assert row.notes, f"{label}.{code} must document why it is unknown"


@pytest.mark.parametrize("label", WHOLLY_UNKNOWN_TABLES)
def test_wholly_unknown_vocabularies_claim_no_meanings(engine: Engine, label: str) -> None:
    """`ref_category`, `ref_payment_method`, `ref_ownership` and `ref_lk180` are codes only.

    Not one code in these four has an evidenced meaning, so not one may carry a guess.
    """
    seed_reference_tables(engine)
    model = _MODEL_BY_LABEL[label]
    with Session(engine) as session:
        rows = list(session.execute(select(model)).scalars())
    assert rows, f"{label} should be seeded"
    for row in rows:
        assert row.meaning is None, f"{label}.{row.code} must not claim a meaning"
        assert row.source == UNKNOWN, f"{label}.{row.code} must be marked unknown"


def test_evidenced_codes_do_carry_meanings(engine: Engine) -> None:
    """Honesty about ignorance must not slide into refusing to state what is known.

    A/T/S are evidenced by exact cross-field consistency with the termination and
    suspension dates, and GP is the target segment. If these lost their meanings the
    vocabulary would be useless.
    """
    seed_reference_tables(engine)
    with Session(engine) as session:
        for label, code in (("ref_status", "A"), ("ref_status", "T"), ("ref_status", "S")):
            row = session.get(_MODEL_BY_LABEL[label], code)
            assert row is not None and row.meaning, f"{label}.{code} is evidenced"
            assert row.source == INFERRED

        gp = session.get(_MODEL_BY_LABEL["ref_provider_type"], "GP")
        assert gp is not None
        assert gp.meaning == "General practitioner / primary care clinic"


def test_backfill_row_counts_records_observed_counts(engine: Engine, seeded_bronze: str) -> None:
    """Observed row counts land on the reference rows; absent codes record zero."""
    backfill_row_counts(engine, seeded_bronze)
    with Session(engine) as session:
        provider_types = {
            row.code: row.row_count
            for row in session.execute(select(_MODEL_BY_LABEL["ref_provider_type"])).scalars()
        }
    # The synthetic fixture holds eight GP rows and no `FT` row at all.
    assert provider_types["GP"] == 8
    assert provider_types["FT"] == 0
    assert all(count is not None for count in provider_types.values())


# --------------------------------------------------------------------------------------
# The unknown-code guard
# --------------------------------------------------------------------------------------


def test_assert_codes_known_passes_on_the_synthetic_extract(
    engine: Engine, seeded_bronze: str
) -> None:
    """Every code in the fixture is declared, so the guard passes and reports what it saw."""
    observed = assert_codes_known(engine, seeded_bronze)

    assert set(observed) == {spec.label for spec in REF_TABLES}
    assert observed["ref_provider_type"] == ["DT", "GP", "OP", "PH", "SP"]
    assert observed["ref_status"] == ["A", "S", "T", "V"]
    for spec in REF_TABLES:
        assert set(observed[spec.label]) <= declared_codes(engine, spec), spec.label


def test_assert_codes_known_raises_on_an_undeclared_code(
    engine: Engine, seeded_bronze: str
) -> None:
    """An undeclared PROVIDER_TYPE_CODE breaks the build, actionably.

    The message must name the offending table, the code and the row count, because the
    fix is a human decision — agree the meaning with PNM, add a seed with an honest
    `source`, and record any residual uncertainty as an open question.
    """
    assert_codes_known(engine, seeded_bronze)  # clean before injection

    _inject_row(
        engine,
        seeded_bronze,
        PROVIDER_CODE="GRIDXX9999",
        PROVIDER_DESCRIPTION="KLINIK CONTOH UNDECLARED",
        PROVIDER_TYPE_CODE=UNDECLARED_PROVIDER_TYPE,
        STATE_CODE="SL",
        STATUS_CODE="A",
        CATEGORY_CODE="P",
        PAYMENT_METHOD_CODE="C",
    )

    with pytest.raises(UnknownCodeError) as excinfo:
        assert_codes_known(engine, seeded_bronze)

    message = str(excinfo.value)
    assert "ref_provider_type" in message, "the offending table must be named"
    assert "PROVIDER_TYPE_CODE" in message, "the source column must be named"
    assert UNDECLARED_PROVIDER_TYPE in message, "the offending code must be named"
    assert "1 rows" in message, "the row count must be reported"
    assert "src/grid/pr001/reference.py" in message, "the message must say where to fix it"


def test_undeclared_code_is_reported_with_its_true_row_count(
    engine: Engine, seeded_bronze: str
) -> None:
    """The reported count is the number of rows actually carrying the code."""
    for offset in range(3):
        _inject_row(
            engine,
            seeded_bronze,
            INJECTED_ROW_ORDINAL + offset,
            PROVIDER_CODE=f"GRIDXX999{offset}",
            PROVIDER_TYPE_CODE=UNDECLARED_PROVIDER_TYPE,
        )

    with pytest.raises(UnknownCodeError, match=r"3 rows"):
        assert_codes_known(engine, seeded_bronze)


def test_guard_covers_every_reference_table(engine: Engine, seeded_bronze: str) -> None:
    """Each vocabulary's source column is guarded, not only the provider type."""
    undeclared_by_column = {
        "PROVIDER_TYPE_CODE": "QQ",
        "STATE_CODE": "QQ",
        "STATUS_CODE": "Q",
        "CATEGORY_CODE": "Q",
        "PAYMENT_METHOD_CODE": "Q",
        "OWNERSHIP_CODE": "9",
        "id_LK180": 9,
    }
    for spec in REF_TABLES:
        planted = undeclared_by_column[spec.source_column]
        assert str(planted) not in declared_codes(engine, spec), (
            f"{spec.label}: the test's planted code must genuinely be undeclared"
        )

    for ordinal, (column, value) in enumerate(undeclared_by_column.items()):
        _inject_row(engine, seeded_bronze, INJECTED_ROW_ORDINAL + ordinal, **{column: value})

    with pytest.raises(UnknownCodeError) as excinfo:
        assert_codes_known(engine, seeded_bronze)

    message = str(excinfo.value)
    for spec in REF_TABLES:
        assert spec.label in message, f"{spec.label} must be reported"


def test_blank_and_null_codes_are_not_treated_as_codes(engine: Engine, seeded_bronze: str) -> None:
    """PR001 uses NULL and blank interchangeably, so neither may be read as a code.

    A blank promoted to a code would make the guard fire on every extract; treating it as
    absent is what keeps the guard's signal meaningful.
    """
    _inject_row(engine, seeded_bronze, INJECTED_ROW_ORDINAL, PROVIDER_TYPE_CODE="   ")
    _inject_row(engine, seeded_bronze, INJECTED_ROW_ORDINAL + 1, STATE_CODE=None)

    assert_codes_known(engine, seeded_bronze)

    seen = observed_codes(engine, "PROVIDER_TYPE_CODE", seeded_bronze)
    assert "" not in seen
    assert "   " not in seen


def test_observed_codes_is_scoped_to_one_generation(engine: Engine, seeded_bronze: str) -> None:
    """A code in another generation is invisible — bronze holds generations side by side."""
    _inject_row(engine, "some-other-generation", 0, PROVIDER_TYPE_CODE=UNDECLARED_PROVIDER_TYPE)

    assert UNDECLARED_PROVIDER_TYPE not in observed_codes(
        engine, "PROVIDER_TYPE_CODE", seeded_bronze
    )
    assert_codes_known(engine, seeded_bronze)
