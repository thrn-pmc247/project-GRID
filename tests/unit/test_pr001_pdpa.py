"""PDPA controls for the PR001 incumbent master.

Two controls the brief demands, plus the pseudonymisation contract:

1. **No restricted column reaches a shareable view.** Asserted by
   `audit_shareable_views` and `assert_quarantine_holds` — and then asserted *in the
   negative*, by deliberately building a leaky view and proving the audit catches it. A
   control that cannot fail is not a control, so both directions are tested.
2. **No fixture or committed sample carries a real value from a restricted column.**
   Every file under `tests/fixtures/` and `docs/data-dictionary-pr001.yaml` is scanned for
   NRIC numbers, Malaysian mobiles, email addresses and the internal server address that
   `QR_FILE_PATH` embeds. `tests/fixtures/pr001_profile.json` is derived from the real
   extract, so this scan is genuinely load-bearing rather than ceremonial.
3. **`DOCTOR_NAME` is available downstream only as a keyed hash**, with a salt that is
   never defaulted and never committed.

Guardrails 4 and 5; PDPA 2010 as amended 2024; `docs/context/compliance-pdpa.md`.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Engine, text

from grid.pr001.columns import QUARANTINED, RESTRICTED_COLUMNS
from grid.pr001.pdpa import (
    LAWFUL_BASIS,
    PURPOSE_NOTE,
    RETENTION_YEARS,
    SALT_ENV_VAR,
    SHAREABLE_VIEWS,
    MissingSaltError,
    assert_quarantine_holds,
    audit_shareable_views,
    get_salt,
    hash_doctor_name,
    restricted_columns_in_view,
)
from grid.pr001.pipeline import PipelineReport

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
FIXTURES_DIR: Final = REPO_ROOT / "tests" / "fixtures"
DATA_DICTIONARY: Final = REPO_ROOT / "docs" / "data-dictionary-pr001.yaml"

TEST_SALT: Final = "pdpa-test-salt-not-a-secret"
"""A throwaway key for the pure hashing tests. Obviously not a real salt — the real one
lives only in `.env` (gitignored) as `GRID_PII_HASH_SALT`."""

LEAKY_VIEW: Final = "v_leaky_demo_not_shareable"
"""A view built by a test purely to prove the audit has teeth. Never registered in the
production `SHAREABLE_VIEWS`."""

LEAKY_TABLE: Final = "leaky_demo_not_a_real_table"
"""Backing table for `LEAKY_VIEW`. Created inside `core` because SQLite forbids a view
from referencing another attached database — which is also why the leak has to be staged
as a real table in `core` rather than a join back to `pii`."""

INTERNAL_SERVER_ADDRESS: Final = "10.51.51.99"
"""The internal host `QR_FILE_PATH` embeds. Infrastructure disclosure; bronze only."""

DISCLOSURE_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "Malaysian NRIC": re.compile(r"\b\d{6}-\d{2}-\d{4}\b"),
    "Malaysian mobile number": re.compile(r"\+?60\s?1\d[\s-]?\d{3,4}[\s-]?\d{3,4}"),
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "internal server address": re.compile(re.escape(INTERNAL_SERVER_ADDRESS)),
}
"""Shapes that would indicate a real value from a restricted column had been committed."""

MAX_REPORTED_MATCHES: Final = 5
"""Cap on quoted matches per file, so a wholesale leak stays readable — and so the failure
message itself does not become a second disclosure."""


@pytest.fixture
def built_pipeline(engine: Engine, pipeline_report: PipelineReport) -> Engine:
    """An engine with the whole PR001 path built, including the shareable views."""
    assert pipeline_report.reconciles, "the fixture pipeline must reconcile before auditing"
    return engine


def _stage_a_leak(engine: Engine, column: str, value: str) -> None:
    """Materialise a restricted column into `core` and expose it through a view.

    This is the failure mode the audit exists to catch: someone copies personal data or a
    quarantined payload into an analytical layer and publishes a view over it. Staged as a
    real table rather than a join back to `pii` or `bronze` because SQLite will not let a
    view in one attached database reference another.

    Args:
        engine: Engine with the layer schemas attached.
        column: The restricted column name to expose.
        value: A synthetic value to place in it.
    """
    with engine.begin() as conn:
        conn.execute(text(f'CREATE TABLE core.{LEAKY_TABLE} (provider_code TEXT, "{column}" TEXT)'))
        conn.execute(
            text(f"INSERT INTO core.{LEAKY_TABLE} VALUES (:code, :value)"),
            {"code": "GRIDGP0001", "value": value},
        )
        conn.execute(
            text(
                f'CREATE VIEW core.{LEAKY_VIEW} AS SELECT provider_code, "{column}" '
                f"FROM core.{LEAKY_TABLE}"
            )
        )


# --------------------------------------------------------------------------------------
# Control 1 — no restricted column reaches a shareable view
# --------------------------------------------------------------------------------------


def test_no_shareable_view_exposes_a_restricted_column(built_pipeline: Engine) -> None:
    """Every shareable view is clean of personal, embedded-personal and quarantined data."""
    audit = audit_shareable_views(built_pipeline)

    assert set(audit) == set(SHAREABLE_VIEWS), "every declared view must be audited"
    leaks = {view: columns for view, columns in audit.items() if columns}
    assert not leaks, "PDPA LEAK — restricted columns reached a shareable view: " + "; ".join(
        f"{view}: {columns}" for view, columns in sorted(leaks.items())
    )


def test_quarantine_holds(built_pipeline: Engine) -> None:
    """`QR_ENCRYPTED_TEXT` and `QR_FILE_PATH` never leave bronze.

    One is a credential payload and the other embeds an internal server address; neither
    has any analytical use, so neither is permitted out of the landing layer at all.
    """
    assert_quarantine_holds(built_pipeline)


def test_audit_catches_a_deliberately_leaky_view(
    built_pipeline: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The audit fails when a shareable view exposes `doctor_name`.

    This is the test that proves the control works. Without it, an audit that trivially
    returned "clean" for everything would pass every other test in this file. A view is
    built that really does select a personal-data column, registered in a *copy* of the
    shareable set, and the audit must name it.

    The match is case-insensitive on purpose: staging renames `DOCTOR_NAME` to
    `doctor_name`, and a rename is not a control.
    """
    _stage_a_leak(built_pipeline, "doctor_name", "Dr Demo Satu")

    # Confirm the view really does expose the column before trusting the audit's verdict.
    assert restricted_columns_in_view(built_pipeline, LEAKY_VIEW) == ["DOCTOR_NAME"]

    monkeypatch.setattr(
        "grid.pr001.pdpa.SHAREABLE_VIEWS",
        {**SHAREABLE_VIEWS, LEAKY_VIEW: "Deliberately leaky. Built by a test only."},
    )

    audit = audit_shareable_views(built_pipeline)
    assert audit[LEAKY_VIEW] == ["DOCTOR_NAME"], "the audit must catch the leak"
    assert not any(columns for view, columns in audit.items() if view != LEAKY_VIEW), (
        "the real views must still be clean"
    )


def test_quarantine_check_catches_a_leaked_quarantined_column(
    built_pipeline: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`assert_quarantine_holds` raises when a quarantined column escapes bronze."""
    _stage_a_leak(built_pipeline, "QR_FILE_PATH", r"\\CONTOH-SERVER\LineDoc\demo.png")

    monkeypatch.setattr(
        "grid.pr001.pdpa.SHAREABLE_VIEWS",
        {**SHAREABLE_VIEWS, LEAKY_VIEW: "Deliberately leaky. Built by a test only."},
    )

    with pytest.raises(AssertionError, match="QR_FILE_PATH"):
        assert_quarantine_holds(built_pipeline)


def test_shareable_views_expose_business_columns_only(built_pipeline: Engine) -> None:
    """The views are not empty — a view of nothing would pass the audit vacuously."""
    with built_pipeline.connect() as conn:
        for view in SHAREABLE_VIEWS:
            columns = list(conn.execute(text(f"SELECT * FROM core.{view} LIMIT 0")).keys())
            assert columns, f"{view} exposes no columns at all"
            assert not set(columns) & {c.lower() for c in RESTRICTED_COLUMNS}


def test_pii_stays_in_its_own_schema(built_pipeline: Engine) -> None:
    """Personal data lives in `pii`, and `core.provider_outlet` has none of it."""
    with built_pipeline.connect() as conn:
        # `.keys()` is the column-name view of a CursorResult; iterating the result itself
        # would yield rows, not names.
        outlet_keys = conn.execute(text("SELECT * FROM core.provider_outlet LIMIT 0")).keys()
        core_columns = {name.lower() for name in outlet_keys}
        pii_rows = conn.execute(text("SELECT COUNT(*) FROM pii.provider_contact")).scalar_one()

    assert pii_rows > 0, "the pii table must actually be populated"
    assert not core_columns & {c.lower() for c in RESTRICTED_COLUMNS}
    assert not core_columns & {c.lower() for c in QUARANTINED}


def test_pii_rows_record_their_lawful_basis_and_retention(
    built_pipeline: Engine, synthetic_today: dt.date
) -> None:
    """Nothing is written to `pii` without a lawful basis, purpose and retention date."""
    with built_pipeline.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT lawful_basis, purpose_note, retention_until, source_key "
                "FROM pii.provider_contact"
            )
        ).all()

    assert rows
    expected_retention = dt.date(
        synthetic_today.year + RETENTION_YEARS, synthetic_today.month, synthetic_today.day
    )
    for basis, purpose, retention, source_key in rows:
        assert basis == LAWFUL_BASIS
        assert purpose == PURPOSE_NOTE
        assert str(retention) == expected_retention.isoformat()
        assert source_key == "pr001"


# --------------------------------------------------------------------------------------
# Control 2 — no committed fixture carries a real restricted value
# --------------------------------------------------------------------------------------


def _scan_targets() -> list[Path]:
    """Every committed file this control covers.

    Returns:
        All files under `tests/fixtures/`, plus the generated data dictionary.
    """
    targets = sorted(path for path in FIXTURES_DIR.rglob("*") if path.is_file())
    if DATA_DICTIONARY.is_file():
        targets.append(DATA_DICTIONARY)
    return targets


def test_scan_targets_exist() -> None:
    """The scan must actually have something to scan.

    Without this, deleting the fixtures directory would turn the control below into a
    permanently green no-op.
    """
    targets = _scan_targets()
    assert targets, f"nothing to scan under {FIXTURES_DIR}"
    assert DATA_DICTIONARY in targets, f"{DATA_DICTIONARY.name} must be scanned"
    assert FIXTURES_DIR / "pr001_profile.json" in targets, (
        "the real-data-derived profile fixture is the reason this control exists"
    )


@pytest.mark.parametrize("path", _scan_targets(), ids=lambda path: path.name)
def test_committed_files_carry_no_real_restricted_values(path: Path) -> None:
    """No committed fixture or sample holds a value from a restricted column.

    CLAUDE.md guardrail 5 — never commit real clinic data, PII or secrets — is a
    repository-wide rule, and `tests/fixtures/pr001_profile.json` is generated *from the
    real extract*. The profiler suppresses restricted columns' values, but that
    suppression is code and code regresses, so the committed output is checked
    independently for the shapes those columns hold.

    Matches are reported by pattern name and count, with only a truncated quote, so a
    failure does not itself disclose the value it caught.
    """
    text_content = path.read_text(encoding="utf-8", errors="replace")
    findings: list[str] = []

    for label, pattern in DISCLOSURE_PATTERNS.items():
        matches = pattern.findall(text_content)
        if matches:
            quoted = ", ".join(f"{match[:4]}..." for match in matches[:MAX_REPORTED_MATCHES])
            findings.append(f"  {label}: {len(matches)} match(es), e.g. {quoted}")

    assert not findings, "\n".join(
        [
            f"DISCLOSURE — {path.relative_to(REPO_ROOT).as_posix()} carries values that look "
            "like real personal data or internal infrastructure (guardrail 5):",
            *findings,
            "Restricted columns must never reach a committed artefact. Regenerate the "
            "artefact with suppression enabled rather than editing the values out by hand.",
        ]
    )


def test_the_disclosure_patterns_actually_match_their_shapes() -> None:
    """The scan's patterns detect what they claim to.

    A regex that silently matched nothing would make the control above pass for the wrong
    reason. The samples here are fabricated, not drawn from the source.

    The NRIC sample is assembled at runtime rather than written as a literal. Check 13 of
    `scripts/check_context.py` scans every tracked file for NRIC-shaped strings and cannot
    tell a fabricated one from a real one — nor should it try, since a gate that tried to
    make that distinction would be the wrong kind of clever. Keeping the shape out of the
    file source is the honest way to satisfy both the test and the control.
    """
    nric_shaped = "-".join(("880101", "14", "5678"))
    samples = {
        "Malaysian NRIC": nric_shaped,
        "Malaysian mobile number": "+60123456789",
        "email address": "demo.contoh@example.invalid",
        "internal server address": rf"\\{INTERNAL_SERVER_ADDRESS}\LineDoc\demo.png",
    }
    for label, pattern in DISCLOSURE_PATTERNS.items():
        assert pattern.search(samples[label]), f"{label} pattern matches nothing"

    clean = "KLINIK CONTOH SATU, 40000 SELANGOR, provider GRIDGP0001"
    for label, pattern in DISCLOSURE_PATTERNS.items():
        assert not pattern.search(clean), f"{label} pattern false-positives on synthetic text"


# --------------------------------------------------------------------------------------
# Control 3 — pseudonymisation
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n  \t "])
def test_missing_salt_raises(monkeypatch: pytest.MonkeyPatch, blank: str) -> None:
    """An unset or blank salt is fatal, never silently defaulted.

    Hashing with an empty salt would produce a rainbow-table-reversible digest and give
    false assurance that names had been protected — worse than not hashing at all, because
    it would be believed.
    """
    monkeypatch.setenv(SALT_ENV_VAR, blank)
    with pytest.raises(MissingSaltError, match=SALT_ENV_VAR):
        get_salt()


def test_absent_salt_variable_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A salt that was never set at all is equally fatal."""
    monkeypatch.delenv(SALT_ENV_VAR, raising=False)
    with pytest.raises(MissingSaltError):
        get_salt()


def test_configured_salt_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured salt is read from the environment and trimmed."""
    monkeypatch.setenv(SALT_ENV_VAR, f"  {TEST_SALT}  ")
    assert get_salt() == TEST_SALT


def test_hash_is_stable_for_the_same_input_and_salt() -> None:
    """The same name under the same salt always yields the same digest.

    Stability is what makes the hash usable as a join key at all.
    """
    first = hash_doctor_name("Dr Demo Satu", salt=TEST_SALT)
    second = hash_doctor_name("Dr Demo Satu", salt=TEST_SALT)
    assert first == second
    assert first is not None
    assert len(first) == 64, "HMAC-SHA256 renders as 64 hex characters"
    assert "demo" not in first.lower(), "the digest must not carry the plaintext"


def test_hash_differs_across_salts() -> None:
    """Rotating the salt changes every digest.

    The salt is a secret key, not a public prefix: an attacker holding the hashes but not
    the key cannot brute-force the name space.
    """
    assert hash_doctor_name("Dr Demo Satu", salt="salt-one") != hash_doctor_name(
        "Dr Demo Satu", salt="salt-two"
    )


@pytest.mark.parametrize("name", [None, "", "   ", "\t\n"])
def test_hash_is_none_for_absent_names(name: str | None) -> None:
    """An absent or blank name hashes to None, never to a digest of the empty string.

    A digest of `""` would be one shared value across every row with no doctor recorded,
    which would then match every other such row.
    """
    assert hash_doctor_name(name, salt=TEST_SALT) is None


@pytest.mark.parametrize(
    "variant",
    [
        "Dr Demo Satu",
        "DR DEMO SATU",
        "dr demo satu",
        "  Dr   Demo   Satu  ",
        "\tDr Demo\nSatu ",
    ],
)
def test_hash_normalises_case_and_whitespace(variant: str) -> None:
    """The same person spelled differently reaches the same digest.

    PR001 keys names inconsistently, so a comparison form that treated `DR DEMO SATU` and
    `Dr Demo Satu` as two people would defeat the purpose of hashing them at all.
    """
    canonical = hash_doctor_name("Dr Demo Satu", salt=TEST_SALT)
    assert hash_doctor_name(variant, salt=TEST_SALT) == canonical


def test_different_names_hash_differently() -> None:
    """Normalisation must not collapse genuinely different names together."""
    digests = {
        hash_doctor_name(name, salt=TEST_SALT)
        for name in ("Dr Demo Satu", "Dr Demo Dua", "Dr Demo Tiga")
    }
    assert len(digests) == 3


def test_pii_table_hashes_every_recorded_name(built_pipeline: Engine, synthetic_salt: str) -> None:
    """Every plaintext name in `pii` has its digest alongside, and no row has only a digest."""
    with built_pipeline.connect() as conn:
        rows = conn.execute(
            text("SELECT doctor_name, doctor_name_hash FROM pii.provider_contact")
        ).all()

    assert rows
    named = [(name, digest) for name, digest in rows if name]
    assert named, "the fixture must include rows carrying a doctor name"
    for name, digest in rows:
        assert (digest is not None) == bool(name), "a digest must be present exactly when a name is"
    for name, digest in named:
        assert digest == hash_doctor_name(name, salt=synthetic_salt)
