"""PDPA controls for the PR001 incumbent master.

Three controls, each independently testable:

1. **Segregation.** Personal data lives in the `pii` schema, never in `core`. The
   default analytical views exclude it (guardrail 4, PDPA 2010 as amended 2024).
2. **Pseudonymisation.** `DOCTOR_NAME` is available downstream only as a salted hash.
   The plaintext column is access-controlled and the salt lives outside the repository
   in `GRID_PII_HASH_SALT`.
3. **Quarantine.** `QR_ENCRYPTED_TEXT` (a credential payload) and `QR_FILE_PATH` (which
   embeds an internal server address) never leave bronze at all.

A view is "shareable" only if it appears in `SHAREABLE_VIEWS`. The tests assert that no
restricted column reaches one, in both directions — a view that quietly gains a personal
column fails the build, and so does a column silently reclassified as business.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
from collections.abc import Mapping, Sequence
from typing import Final

import structlog
from sqlalchemy import Engine, delete, insert, select, text
from sqlalchemy.orm import Session

from grid.db.models import PiiProviderContact, pr001_provider_master
from grid.pr001.columns import (
    PERSONAL_DATA_COLUMNS,
    QUARANTINED,
    RESTRICTED_COLUMNS,
)

log = structlog.get_logger(__name__)

SALT_ENV_VAR: Final = "GRID_PII_HASH_SALT"

RETENTION_YEARS: Final = 7
"""Retention for provider contact data, aligned to the commercial record it supports.
Provisional — open question 5 asks whether PMCare has an existing PDPA processing
register and retention schedule GRID must align to instead."""

LAWFUL_BASIS: Final = (
    "Performance of the provider panel contract and PMCare's legitimate interest as a "
    "licensed TPA/MCO in administering its provider network. Recorded per row at write "
    "time; requires DPO confirmation (open question 5)."
)

PURPOSE_NOTE: Final = (
    "Provider network administration and panel engagement. Not used for marketing; no "
    "automated outreach (guardrail 6)."
)

SHAREABLE_VIEWS: Final[Mapping[str, str]] = {
    "v_provider_outlet_shareable": (
        "Default analytical view of the incumbent network. Business data only."
    ),
    "v_kpi_appointments_monthly": ("Monthly appointment counts by provider type. Aggregate only."),
    "v_chain_summary": "Inferred chain groupings with outlet counts.",
}
"""Views that may be exposed to analysts or exported. Anything absent is not shareable."""

# Business-classed columns of core.provider_outlet. Stated explicitly rather than
# `SELECT *` so that adding a column to the table cannot silently widen the view.
_SHAREABLE_OUTLET_COLUMNS: Final[tuple[str, ...]] = (
    "provider_code",
    "name_normalised",
    "chain_base_name",
    "branch_qualifier",
    "address_locality",
    "city_canonical",
    "postcode_clean",
    "postcode_valid",
    "state_code",
    "postcode_state_mismatch",
    "latitude_clean",
    "longitude_clean",
    "coord_quality",
    "provider_type_code",
    "status_code",
    "pmcare_panel_status",
    "appointment_date",
    "termination_date",
    "suspension_date",
    "operating_hours_present",
)


class MissingSaltError(RuntimeError):
    """The PII hash salt is not configured.

    Deliberately fatal: hashing with a default or empty salt would produce a rainbow-
    table-reversible digest and give false assurance that names had been protected.
    """


def get_salt() -> str:
    """Read the hash salt from the environment.

    Raises:
        MissingSaltError: when unset or blank.
    """
    salt = os.environ.get(SALT_ENV_VAR, "").strip()
    if not salt:
        raise MissingSaltError(
            f"{SALT_ENV_VAR} is not set. Doctor names are hashed with a keyed digest; "
            "an empty salt would make the hash trivially reversible. Set it in .env "
            "(gitignored) — never commit it."
        )
    return salt


def hash_doctor_name(name: str | None, *, salt: str) -> str | None:
    """Return a salted, keyed hash of a doctor's name, or None when absent.

    HMAC-SHA256 rather than a plain salted digest: the salt is a secret key, so an
    attacker holding the hashes but not the key cannot brute-force the name space.
    Normalised to casefolded, whitespace-collapsed form first so that the same person
    spelled differently still matches.
    """
    if name is None:
        return None
    normalised = " ".join(name.split()).casefold()
    if not normalised:
        return None
    return hmac.new(salt.encode("utf-8"), normalised.encode("utf-8"), hashlib.sha256).hexdigest()


def populate_pii(engine: Engine, ingest_id: str, *, salt: str, today: dt.date) -> int:
    """Extract personal data from bronze into `pii.provider_contact`.

    Every row records `lawful_basis`, `retention_until` and `purpose_note` at write
    time, matching the `practitioner` contract in `docs/context/data-model.md`. Nothing
    is written without them.
    """
    columns = ("PROVIDER_CODE", *PERSONAL_DATA_COLUMNS)
    stmt = (
        select(*(pr001_provider_master.c[c] for c in columns))
        .where(pr001_provider_master.c._ingest_id == ingest_id)
        .order_by(pr001_provider_master.c._row_ordinal)
    )

    def clean(value: object) -> str | None:
        if value is None:
            return None
        return str(value).strip() or None

    retention_until = dt.date(today.year + RETENTION_YEARS, today.month, today.day)
    rows: list[dict[str, object]] = []

    with engine.connect() as conn:
        for row in conn.execute(stmt):
            data = row._mapping
            doctor_name = clean(data["DOCTOR_NAME"])
            rows.append(
                {
                    "provider_code": str(data["PROVIDER_CODE"]).strip(),
                    "doctor_name": doctor_name,
                    "doctor_name_hash": hash_doctor_name(doctor_name, salt=salt),
                    "general_phone_no": clean(data["GENERAL_PHONE_NO"]),
                    "apps_phone_no": clean(data["APPS_PHONE_NO"]),
                    "einv_email": clean(data["einv_email"]),
                    "einv_tin_no": clean(data["einv_tin_no"]),
                    "einv_sst_no": clean(data["einv_sst_no"]),
                    "hbrn": clean(data["HBRN"]),
                    "gst_company_reg_no": clean(data["GST_COMPANY_REG_NO"]),
                    "lawful_basis": LAWFUL_BASIS,
                    "retention_until": retention_until,
                    "purpose_note": PURPOSE_NOTE,
                    "source_key": "pr001",
                }
            )

    with Session(engine) as session:
        session.execute(delete(PiiProviderContact))
        session.commit()

    with engine.begin() as conn:
        for start in range(0, len(rows), 2_000):
            conn.execute(insert(PiiProviderContact), rows[start : start + 2_000])

    log.info("pdpa.pii_populated", rows=len(rows))
    return len(rows)


def create_shareable_views(engine: Engine) -> None:
    """Create the analytical views that exclude personal data.

    `v_kpi_appointments_monthly` is created by `grid.pr001.core`; this function creates
    the other two so that all shareable views are defined against the same explicit
    column allow-list.
    """
    outlet_columns = ",\n    ".join(f"o.{c}" for c in _SHAREABLE_OUTLET_COLUMNS)
    statements = (
        f"""
        CREATE VIEW core.v_provider_outlet_shareable AS
        SELECT
            {outlet_columns}
        FROM core.provider_outlet AS o
        """,
        """
        CREATE VIEW core.v_chain_summary AS
        SELECT
            c.chain_base_name,
            c.outlet_count,
            c.source,
            COUNT(m.provider_code) AS members
        FROM core.chain AS c
        LEFT JOIN core.outlet_chain_member AS m ON m.chain_id = c.chain_id
        GROUP BY c.chain_base_name, c.outlet_count, c.source
        """,
    )
    with engine.begin() as conn:
        for name in ("v_provider_outlet_shareable", "v_chain_summary"):
            conn.execute(text(f"DROP VIEW IF EXISTS core.{name}"))
        for sql in statements:
            conn.execute(text(sql))


def view_columns(engine: Engine, view_name: str, schema: str = "core") -> Sequence[str]:
    """Column names of a view, as the database reports them."""
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT * FROM {schema}.{view_name} LIMIT 0"))
        return list(result.keys())


def restricted_columns_in_view(engine: Engine, view_name: str) -> list[str]:
    """Restricted source columns exposed by a shareable view.

    Matching is case-insensitive on the source column name, because staging renames
    `DOCTOR_NAME` to `doctor_name`. A rename is not a control.
    """
    exposed = {c.lower() for c in view_columns(engine, view_name)}
    return sorted(c for c in RESTRICTED_COLUMNS if c.lower() in exposed)


def audit_shareable_views(engine: Engine) -> Mapping[str, list[str]]:
    """Check every shareable view for restricted columns.

    Returns:
        View name to the restricted columns it exposes. All-empty lists means clean.
    """
    return {name: restricted_columns_in_view(engine, name) for name in SHAREABLE_VIEWS}


def assert_quarantine_holds(engine: Engine) -> None:
    """Assert the quarantined columns exist in bronze and nowhere else.

    Raises:
        AssertionError: when a quarantined column has leaked out of bronze.
    """
    leaked: list[str] = []
    for view_name in SHAREABLE_VIEWS:
        exposed = {c.lower() for c in view_columns(engine, view_name)}
        leaked.extend(c for c in QUARANTINED if c.lower() in exposed)
    if leaked:
        raise AssertionError(
            f"Quarantined columns reached a shareable view: {sorted(set(leaked))}. "
            "QR_ENCRYPTED_TEXT is a credential payload and QR_FILE_PATH embeds an "
            "internal server address; both are bronze-only."
        )
