"""Reference tables for PR001's code vocabularies, and the unknown-code guard.

Two rules govern this module.

**Seed only what the data evidences.** A meaning is recorded as `confirmed_by_pnm` only
when a person has confirmed it, `inferred` when we are reading a code abbreviation in the
obvious way, and `unknown` — with `meaning` left NULL — when we genuinely do not know.
Guardrail 10 forbids inventing meanings, and a NULL with a documented reason is worth
more than a plausible guess.

**The declared vocabulary is fixed.** These seeds enumerate every code present in the
2026-08-05 extract. They are *not* discovered from the data at load time, because a
vocabulary that grows itself can never detect growth. A code appearing in a future
extract that is absent here raises `UnknownCodeError` and breaks the build — which is
the point. A new provider type is a business change that needs a human decision, not a
NULL flowing quietly into staging.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import structlog
from sqlalchemy import Engine, Select, func, select
from sqlalchemy.orm import Session

from grid.db.models import (
    RefCategory,
    RefLk180,
    RefOwnership,
    RefPaymentMethod,
    RefProviderType,
    RefState,
    RefStatus,
    pr001_provider_master,
)

log = structlog.get_logger(__name__)

RefTableModel = (
    RefProviderType
    | RefState
    | RefStatus
    | RefCategory
    | RefPaymentMethod
    | RefOwnership
    | RefLk180
)
"""Any of the seven code reference models.

They share their whole shape via `_RefMixin` but not a common declarative base below
`Base`, so a query over `RefTableSpec.model` is annotated against this union rather than
against `Base` — otherwise `code` and `row_count` are invisible to the type checker.
"""

CONFIRMED_BY_PNM: Final = "confirmed_by_pnm"
INFERRED: Final = "inferred"
UNKNOWN: Final = "unknown"


class UnknownCodeError(RuntimeError):
    """A code appeared in the source that no reference table declares.

    Deliberately fatal. See the module docstring.
    """


@dataclass(frozen=True, slots=True)
class RefSeed:
    """One declared code."""

    code: str
    meaning: str | None
    source: str
    notes: str | None = None


# --- ref_status ----------------------------------------------------------------------
# A, T and S are evidenced, not guessed: TERMINATION_DATE is populated for exactly the
# 4,032 'T' rows and SUSPENSION_DATE for exactly the 17 'S' rows — nil code-without-date
# and nil date-without-code in both directions. That cross-field consistency is the
# evidence. 'V' has 3 rows and no corroborating date column, so it stays unknown.
STATUS_SEEDS: Final[tuple[RefSeed, ...]] = (
    RefSeed(
        "A",
        "Active",
        INFERRED,
        "29,591 rows. Evidenced by absence of termination/suspension dates.",
    ),
    RefSeed(
        "T",
        "Terminated",
        INFERRED,
        "4,032 rows, matching TERMINATION_DATE exactly (0 mismatches).",
    ),
    RefSeed(
        "S",
        "Suspended",
        INFERRED,
        "17 rows, matching SUSPENSION_DATE exactly (0 mismatches).",
    ),
    RefSeed(
        "V",
        None,
        UNKNOWN,
        "3 rows (989896, 989898, 989899). Neither terminated nor suspended. "
        "Meaning unknown — open question.",
    ),
)

# --- ref_provider_type ---------------------------------------------------------------
# Seven codes are read in the obvious way and marked inferred. The remaining fourteen
# have no defensible reading, so they carry NULL meanings and are raised as an open
# question rather than guessed at.
PROVIDER_TYPE_SEEDS: Final[tuple[RefSeed, ...]] = (
    RefSeed(
        "GP",
        "General practitioner / primary care clinic",
        INFERRED,
        "13,552 rows. GRID's target segment.",
    ),
    RefSeed("OP", "Optical", INFERRED, "7,000 rows."),
    RefSeed("DT", "Dental", INFERRED, "5,140 rows. Out of GRID scope (guardrail 7)."),
    RefSeed("SP", "Specialist", INFERRED, "2,573 rows. Out of GRID scope."),
    RefSeed("PH", "Pharmacy", INFERRED, "1,115 rows."),
    RefSeed("LB", "Laboratory", INFERRED, "776 rows. Out of GRID scope."),
    RefSeed("HP", "Hospital", INFERRED, "657 rows. Out of GRID scope."),
    RefSeed("WP", None, UNKNOWN, "720 rows. Meaning unknown — open question."),
    RefSeed("AM", None, UNKNOWN, "690 rows. Meaning unknown — open question."),
    RefSeed("MS", None, UNKNOWN, "637 rows. Meaning unknown — open question."),
    RefSeed("FS", None, UNKNOWN, "442 rows. Meaning unknown — open question."),
    RefSeed("DC", None, UNKNOWN, "279 rows. Meaning unknown — open question."),
    RefSeed("TD", None, UNKNOWN, "22 rows. Meaning unknown — open question."),
    RefSeed("NA", None, UNKNOWN, "17 rows. Meaning unknown — open question."),
    RefSeed("CL", None, UNKNOWN, "9 rows. Meaning unknown — open question."),
    RefSeed("IM", None, UNKNOWN, "6 rows. Meaning unknown — open question."),
    RefSeed("MT", None, UNKNOWN, "2 rows. Meaning unknown — open question."),
    RefSeed("CP", None, UNKNOWN, "2 rows. Meaning unknown — open question."),
    RefSeed("PT", None, UNKNOWN, "2 rows. Meaning unknown — open question."),
    RefSeed("PM", None, UNKNOWN, "1 row. Meaning unknown — open question."),
    RefSeed("FT", None, UNKNOWN, "1 row. Meaning unknown — open question."),
)

# --- ref_state -----------------------------------------------------------------------
# Fifteen codes read as 13 states plus the federal territories of Kuala Lumpur and
# Labuan. Putrajaya, the third federal territory, is otherwise absent — which is the
# reason PJ is flagged rather than assumed.
STATE_SEEDS: Final[tuple[RefSeed, ...]] = (
    RefSeed("SL", "Selangor", INFERRED, "10,220 rows."),
    RefSeed("KL", "Wilayah Persekutuan Kuala Lumpur", INFERRED, "5,813 rows."),
    RefSeed("JB", "Johor", INFERRED, "3,431 rows."),
    RefSeed("PR", "Perak", INFERRED, "2,247 rows."),
    RefSeed("PG", "Pulau Pinang", INFERRED, "2,080 rows."),
    RefSeed("SR", "Sarawak", INFERRED, "1,531 rows."),
    RefSeed("SB", "Sabah", INFERRED, "1,420 rows."),
    RefSeed("KD", "Kedah", INFERRED, "1,419 rows."),
    RefSeed("NS", "Negeri Sembilan", INFERRED, "1,351 rows."),
    RefSeed("PH", "Pahang", INFERRED, "1,079 rows."),
    RefSeed("ML", "Melaka", INFERRED, "1,069 rows."),
    RefSeed("KN", "Kelantan", INFERRED, "901 rows."),
    RefSeed("TR", "Terengganu", INFERRED, "751 rows."),
    RefSeed("PE", "Perlis", INFERRED, "136 rows."),
    RefSeed("LA", "Wilayah Persekutuan Labuan", INFERRED, "47 rows."),
    RefSeed(
        "PJ",
        "Wilayah Persekutuan Putrajaya",
        INFERRED,
        "118 rows. PROBABLY Putrajaya — Putrajaya is otherwise absent from the code set, "
        "which is suggestive but not proof. Open question; do not rely on it for "
        "state-level reporting until PNM confirms.",
    ),
    RefSeed(
        "ZZ",
        None,
        UNKNOWN,
        "29 rows. Not a Malaysian state. Meaning unknown — open question.",
    ),
    RefSeed(
        "00",
        None,
        UNKNOWN,
        "1 row. Not a Malaysian state. Meaning unknown — open question.",
    ),
)

# --- vocabularies with no evidenced meanings at all -----------------------------------
CATEGORY_SEEDS: Final[tuple[RefSeed, ...]] = tuple(
    RefSeed(code, None, UNKNOWN, f"{count:,} rows. Meaning unknown — open question.")
    for code, count in (
        ("P", 33_322),
        ("G", 244),
        ("C", 28),
        ("A", 21),
        ("F", 12),
        ("U", 11),
        ("X", 5),
    )
)
PAYMENT_METHOD_SEEDS: Final[tuple[RefSeed, ...]] = tuple(
    RefSeed(code, None, UNKNOWN, f"{count:,} rows. Meaning unknown — open question.")
    for code, count in (("C", 19_868), ("M", 11_035), ("X", 2_740))
)
OWNERSHIP_SEEDS: Final[tuple[RefSeed, ...]] = tuple(
    RefSeed(code, None, UNKNOWN, f"{count:,} rows. Meaning unknown — open question.")
    for code, count in (("0", 1_151), ("3", 55), ("2", 51), ("1", 43))
)
LK180_SEEDS: Final[tuple[RefSeed, ...]] = tuple(
    RefSeed(
        code,
        None,
        UNKNOWN,
        f"{count:,} rows. Meaning unknown — what LK180 refers to is unknown.",
    )
    for code, count in (("0", 1_867), ("3", 857), ("2", 120), ("1", 23))
)


@dataclass(frozen=True, slots=True)
class RefTableSpec:
    """Binds a source column to the reference table that declares its vocabulary."""

    model: type[RefTableModel]
    source_column: str
    seeds: tuple[RefSeed, ...]
    label: str


REF_TABLES: Final[tuple[RefTableSpec, ...]] = (
    RefTableSpec(RefProviderType, "PROVIDER_TYPE_CODE", PROVIDER_TYPE_SEEDS, "ref_provider_type"),
    RefTableSpec(RefState, "STATE_CODE", STATE_SEEDS, "ref_state"),
    RefTableSpec(RefStatus, "STATUS_CODE", STATUS_SEEDS, "ref_status"),
    RefTableSpec(RefCategory, "CATEGORY_CODE", CATEGORY_SEEDS, "ref_category"),
    RefTableSpec(
        RefPaymentMethod, "PAYMENT_METHOD_CODE", PAYMENT_METHOD_SEEDS, "ref_payment_method"
    ),
    RefTableSpec(RefOwnership, "OWNERSHIP_CODE", OWNERSHIP_SEEDS, "ref_ownership"),
    RefTableSpec(RefLk180, "id_LK180", LK180_SEEDS, "ref_lk180"),
)


def seed_reference_tables(
    engine: Engine, *, confirmed_at: dt.datetime | None = None
) -> dict[str, int]:
    """Insert the declared vocabularies. Idempotent — existing codes are left alone.

    Returns:
        Rows written per reference table.
    """
    written: dict[str, int] = {}
    with Session(engine) as session:
        for spec in REF_TABLES:
            existing = {c for (c,) in session.execute(select(spec.model.code))}
            rows = 0
            for seed in spec.seeds:
                if seed.code in existing:
                    continue
                session.add(
                    spec.model(
                        code=seed.code,
                        meaning=seed.meaning,
                        source=seed.source,
                        confirmed_by=None,
                        confirmed_at=confirmed_at if seed.source == CONFIRMED_BY_PNM else None,
                        notes=seed.notes,
                        row_count=None,
                    )
                )
                rows += 1
            written[spec.label] = rows
        session.commit()
    log.info("reference.seeded", **written)
    return written


def observed_codes(engine: Engine, column: str, ingest_id: str) -> set[str]:
    """Distinct non-null, non-blank values of `column` in one bronze generation.

    Blank strings are treated as absent, not as a code — PR001 uses them
    interchangeably with NULL across most columns.
    """
    col = pr001_provider_master.c[column]
    stmt = (
        select(col)
        .where(pr001_provider_master.c._ingest_id == ingest_id)
        .where(col.is_not(None))
        .distinct()
    )
    with engine.connect() as conn:
        values = {row[0] for row in conn.execute(stmt)}
    return {str(v).strip() for v in values if str(v).strip() != ""}


def declared_codes(engine: Engine, spec: RefTableSpec) -> set[str]:
    """Codes currently declared in a reference table."""
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(select(spec.model.code))}


def assert_codes_known(engine: Engine, ingest_id: str) -> Mapping[str, Sequence[str]]:
    """Raise `UnknownCodeError` if any source code is undeclared.

    This is the guard the brief asks for: staging must never encounter a code that no
    reference table knows about. Called at the top of the staging transform, so an
    unrecognised code fails the build rather than flowing through as NULL.

    Returns:
        Per reference table, the codes actually observed — useful for logging.

    Raises:
        UnknownCodeError: listing every offending table, code and row count.
    """
    observed: dict[str, Sequence[str]] = {}
    problems: list[str] = []

    for spec in REF_TABLES:
        seen = observed_codes(engine, spec.source_column, ingest_id)
        observed[spec.label] = sorted(seen)
        undeclared = sorted(seen - declared_codes(engine, spec))
        if undeclared:
            counts = _code_counts(engine, spec.source_column, ingest_id, undeclared)
            detail = ", ".join(f"{code!r} ({counts.get(code, 0):,} rows)" for code in undeclared)
            problems.append(f"{spec.label} (from {spec.source_column}): undeclared {detail}")

    if problems:
        raise UnknownCodeError(
            "Source codes are not declared in their reference tables:\n  "
            + "\n  ".join(problems)
            + "\n\nThis is deliberate. A new code is a business change: decide what it "
            "means with PNM, add it to src/grid/pr001/reference.py with an honest "
            "`source` value, and record any uncertainty in "
            "docs/context/open-questions.md. Do not let it through as NULL."
        )
    return observed


def _code_counts(
    engine: Engine, column: str, ingest_id: str, codes: Sequence[str]
) -> dict[str, int]:
    """Row counts for specific codes, so the error message is actionable."""
    col = pr001_provider_master.c[column]
    stmt = (
        select(col, func.count())
        .where(pr001_provider_master.c._ingest_id == ingest_id)
        .where(col.in_(list(codes)))
        .group_by(col)
    )
    with engine.connect() as conn:
        return {str(code): int(count) for code, count in conn.execute(stmt)}


def backfill_row_counts(engine: Engine, ingest_id: str) -> None:
    """Record observed row counts on each reference row. Informational only.

    Every count is read *before* the session opens. `_code_counts` and `declared_codes`
    each check out their own connection, and on an in-memory SQLite engine that is a
    `StaticPool` — the same DBAPI connection the session is using. Closing it part-way
    through the loop rolled the session's pending updates back, so all but the last
    vocabulary silently kept `row_count` NULL. Reading first keeps the write phase free of
    any nested connection.
    """
    counts_by_label = {
        spec.label: _code_counts(
            engine, spec.source_column, ingest_id, sorted(declared_codes(engine, spec))
        )
        for spec in REF_TABLES
    }

    with Session(engine) as session:
        for spec in REF_TABLES:
            counts = counts_by_label[spec.label]
            # Annotated against the concrete union: `spec.model` is a `type[RefTableModel]`,
            # and without the type context mypy widens the entity to `Base`, which declares
            # neither `code` nor `row_count`.
            stmt: Select[tuple[RefTableModel]] = select(spec.model)
            for row in session.execute(stmt).scalars():
                row.row_count = counts.get(row.code, 0)
        session.commit()
