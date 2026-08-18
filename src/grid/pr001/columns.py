"""The PR001 column contract — single source of truth for all 70 source columns.

Every downstream layer reads its rules from here rather than restating them:

* `tools/profile_parquet.py` suppresses value samples for restricted columns.
* The bronze loader asserts the source file still carries exactly `SOURCE_COLUMNS`.
* Staging drops `Disposition.DROP` columns at its boundary and never selects
  `Disposition.QUARANTINE` ones.
* The PDPA tests assert no restricted column reaches a shareable view.
* `docs/data-dictionary-pr001.yaml` is generated from this module plus a profile.

Dispositions and PDPA classes are stated by the brief and corroborated by profiling
(`docs/reconciliation-pr001.md` §7). Where this module departs from the brief's list the
`note` records why — see `WEBSITE`, `REMARKS`, `SYS_ADMIN_REMARKS`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class Disposition(StrEnum):
    """What happens to a source column on the way out of bronze."""

    KEEP = "keep"
    """Carried into staging."""

    DROP = "drop"
    """Lands in bronze verbatim, dropped at the staging boundary — no information content."""

    QUARANTINE = "quarantine"
    """Bronze only. Never reaches an analytical or shareable layer at all."""

    PII = "pii"
    """Personal data under PDPA 2010. Segregated into the `pii` schema."""


class PdpaClass(StrEnum):
    """PDPA 2010 (as amended 2024) classification, per `docs/context/compliance-pdpa.md`."""

    BUSINESS = "business"
    """Business data about a facility. Default, low risk."""

    PERSONAL = "personal"
    """Identifies a living individual. Full PDPA regime; restricted table."""

    BUSINESS_EMBEDDED_PERSONAL = "business_embedded_personal"
    """Nominally business free text that demonstrably carries individuals' names.

    Treated as restricted for disclosure purposes — excluded from shareable views —
    but still usable inside the pipeline (the REMARKS miner needs it).
    """


class Confidence(StrEnum):
    """Whether a definition is evidenced by the data or inferred by us."""

    EVIDENCED = "evidenced"
    """The data itself demonstrates this (uniqueness, cross-field consistency, fill)."""

    INFERRED = "inferred"
    """Our reading of a column name or value shape. Plausible, unconfirmed."""

    UNKNOWN = "unknown"
    """We do not know what this column means. Flagged as an open question."""


class LogicalType(StrEnum):
    """Parquet logical type as written by Polars, independent of physical storage."""

    STRING = "STRING"
    BOOLEAN = "BOOLEAN"
    INT64 = "INT64"
    DOUBLE = "DOUBLE"
    TIMESTAMP_MICROS = "TIMESTAMP(micros, not UTC-adjusted)"
    TIME_NANOS = "TIME(nanos)"


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """One PR001 source column and every rule that applies to it."""

    name: str
    logical_type: LogicalType
    disposition: Disposition
    pdpa_class: PdpaClass
    confidence: Confidence
    definition: str
    note: str | None = None

    @property
    def restricted(self) -> bool:
        """True when the column must never appear in a shareable view or a fixture.

        Covers personal data, free text with embedded personal data, and the
        quarantined credential/infrastructure columns.
        """
        return (
            self.disposition is Disposition.QUARANTINE or self.pdpa_class is not PdpaClass.BUSINESS
        )


_T = LogicalType
_D = Disposition
_P = PdpaClass
_C = Confidence

# Order is the physical column order in PR001.parquet. The bronze loader depends on it
# for `_row_ordinal` reproducibility and for its column-set assertion.
SOURCE_COLUMN_SPECS: Final[tuple[ColumnSpec, ...]] = (
    ColumnSpec(
        "PROVIDER_CODE",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "PNM's provider identifier. One of only two safe keys.",
        "33,643/33,643 distinct. Not numeric — ranges over GOH, 0101252, DEN4022, PH036; "
        "lengths 5-12. Prefix appears to encode provider type but this is unconfirmed.",
    ),
    ColumnSpec(
        "PROVIDER_DESCRIPTION",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Provider trading name as keyed by PNM.",
        "NOT unique: 3,303 name groups cover 10,426 rows. 4,155 names end in a "
        "parenthesised branch qualifier.",
    ),
    ColumnSpec(
        "HBRN",
        _T.STRING,
        _D.PII,
        _P.PERSONAL,
        _C.UNKNOWN,
        "Unexplained registration-style identifier.",
        "4,796 real values (14%); 13,393 NULL + 15,454 blank. Whether this is the "
        "MOH/PHFSA facility registration number is an open question. Treated as personal "
        "until confirmed, since a sole proprietor's registration identifies an individual.",
    ),
    ColumnSpec(
        "PROVIDER_ALIAS_CODE",
        _T.STRING,
        _D.DROP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Unused alias slot.",
        "Dropped at staging: literal 'NONE' in all 33,643 rows — zero information content.",
    ),
    ColumnSpec(
        "PROVIDER_TYPE_CODE",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Provider discipline code. FK to ref_provider_type.",
        "21 distinct. GP 13,552 · OP 7,000 · DT 5,140 · SP 2,573 · PH 1,115 · LB 776 · "
        "WP 720 · AM 690 · HP 657 · MS 637 · FS 442 · DC 279 · TD 22 · NA 17 · CL 9 · "
        "IM 6 · MT 2 · CP 2 · PT 2 · PM 1 · FT 1. 14 codes unresolved.",
    ),
    ColumnSpec(
        "CATEGORY_CODE",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.UNKNOWN,
        "Unexplained category code. FK to ref_category.",
        "7 distinct: P 33,322 · G 244 · C 28 · A 21 · F 12 · U 11 · X 5. Meanings unknown.",
    ),
    ColumnSpec(
        "PMCARE_PANEL_STATUS",
        _T.BOOLEAN,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Whether the provider is on the PMCare panel. Authoritative for suppression.",
        "GP + STATUS_CODE 'A' + this flag = 5,956 rows.",
    ),
    ColumnSpec(
        "ADDRESS1",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Free-text address line 1.",
        "33,381 real values; 135 NULL + 127 blank.",
    ),
    ColumnSpec(
        "ADDRESS2",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Free-text address line 2.",
        "27,198 real values.",
    ),
    ColumnSpec(
        "ADDRESS3",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Free-text address line 3.",
        "17,929 real values.",
    ),
    ColumnSpec(
        "CITY",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Free-text city/town. Canonicalised via ref_city.",
        "1,019 distinct with no controlled vocabulary; 617 NULL + 1,599 blank.",
    ),
    ColumnSpec(
        "POSTCODE",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Malaysian 5-digit postcode as keyed.",
        "32,834 non-blank, only 32,649 match ^\\d{5}$. Invalids include 814000, 8480, "
        "'CV5 6J' (UK) and encoding corruption. Never coerced to char(5).",
    ),
    ColumnSpec(
        "STATE_CODE",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Two-character state/FT code. FK to ref_state.",
        "18 distinct: 15 plausible (13 states + KL + LA) plus PJ 118, ZZ 29, 00 1. "
        "Putrajaya is absent unless PJ is it. A closed 16-value enum would reject 148 rows.",
    ),
    ColumnSpec(
        "MEDILINE_USER",
        _T.BOOLEAN,
        _D.KEEP,
        _P.BUSINESS,
        _C.INFERRED,
        "Whether the provider uses the Mediline system.",
    ),
    ColumnSpec(
        "OPEN24HOURS",
        _T.BOOLEAN,
        _D.KEEP,
        _P.BUSINESS,
        _C.INFERRED,
        "Whether the provider operates 24 hours.",
    ),
    ColumnSpec(
        "OPEN_PUBLIC_HOLIDAYS",
        _T.BOOLEAN,
        _D.KEEP,
        _P.BUSINESS,
        _C.INFERRED,
        "Whether the provider opens on public holidays.",
    ),
    ColumnSpec(
        "GL_ELIGIBILITY_STATUS",
        _T.BOOLEAN,
        _D.KEEP,
        _P.BUSINESS,
        _C.INFERRED,
        "Guarantee-of-letter eligibility flag.",
    ),
    ColumnSpec(
        "GL_ELIGIBILITY_APPROVE_BY",
        _T.STRING,
        _D.PII,
        _P.PERSONAL,
        _C.EVIDENCED,
        "PMCare staff user ID that approved GL eligibility.",
        "8,912 real values; 24 raw variants fold to 15 people (M_NOOR == m_noor).",
    ),
    ColumnSpec(
        "GL_ELIGIBILITY_APPROVE_DATE",
        _T.TIMESTAMP_MICROS,
        _D.DROP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Date GL eligibility was approved.",
        "Dropped at staging: NULL in all 33,643 rows, even though "
        "GL_ELIGIBILITY_APPROVE_BY is populated for 8,912. The pairing is broken upstream.",
    ),
    ColumnSpec(
        "DOCTOR_NAME",
        _T.STRING,
        _D.PII,
        _P.PERSONAL,
        _C.EVIDENCED,
        "Name of the doctor associated with the provider.",
        "13,496 real values, 11,815 distinct. Available downstream only as a salted hash; "
        "plaintext is access-controlled and the salt lives outside the repo.",
    ),
    ColumnSpec(
        "WEBSITE",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS_EMBEDDED_PERSONAL,
        _C.EVIDENCED,
        "Nominally a website. In practice misused as a free-text contact note.",
        "DEVIATION from the brief's personal-data list: only 83 real values / 73 distinct, "
        "and populated values include staff names ('MS. YAP', 'JAYANTHI'). Because it "
        "demonstrably carries individuals' names it is classed as embedded-personal and "
        "excluded from shareable views. It is not a web-presence signal.",
    ),
    ColumnSpec(
        "VISUAL",
        _T.STRING,
        _D.DROP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Unused.",
        "Dropped at staging: NULL in all 33,643 rows.",
    ),
    ColumnSpec(
        "GENERAL_PHONE_NO",
        _T.STRING,
        _D.PII,
        _P.PERSONAL,
        _C.EVIDENCED,
        "Main contact telephone number.",
        "31,292 real values. Personal by guardrail 4 — a sole proprietor's dual-use "
        "mobile is personal data and cannot be separated from the clinic line here.",
    ),
    ColumnSpec(
        "GENERAL_FAX_NO",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Fax number.",
        "7,621 real values.",
    ),
    ColumnSpec(
        "PAYMENT_METHOD_CODE",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.UNKNOWN,
        "Unexplained payment-method code. FK to ref_payment_method.",
        "3 distinct: C 19,868 · M 11,035 · X 2,740. Meanings unknown.",
    ),
    ColumnSpec(
        "STATUS_CODE",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Provider lifecycle status. FK to ref_status.",
        "A 29,591 · T 4,032 · S 17 · V 3. A/T/S evidenced by exact cross-field "
        "consistency with TERMINATION_DATE and SUSPENSION_DATE. V unknown.",
    ),
    ColumnSpec(
        "STATUS_BY",
        _T.STRING,
        _D.PII,
        _P.PERSONAL,
        _C.EVIDENCED,
        "PMCare staff user ID that last set the status.",
        "76 raw variants fold to 70 people.",
    ),
    ColumnSpec(
        "STATUS_DATE",
        _T.TIMESTAMP_MICROS,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "When the status was last set.",
        "0 NULL, 9,337 distinct.",
    ),
    ColumnSpec(
        "APPOINMENT_DATE",
        _T.TIMESTAMP_MICROS,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Date the provider was appointed to the PMCare network. [sic — source spelling]",
        "0 NULL; 1995-05-02 to 2026-08-05. This is a panel-appointment date, NOT a "
        "facility registration date. Basis of the KPI baseline view.",
    ),
    ColumnSpec(
        "TERMINATION_DATE",
        _T.TIMESTAMP_MICROS,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Date the appointment was terminated.",
        "Populated for exactly the 4,032 STATUS_CODE='T' rows — 0 code-without-date, "
        "0 date-without-code. Reaches 2028-08-05, so future-dated terminations exist "
        "(exactly 1 as at 2026-08-17). Never test IS NULL for activity.",
    ),
    ColumnSpec(
        "SUSPENSION_DATE",
        _T.TIMESTAMP_MICROS,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Date the provider was suspended.",
        "Populated for exactly the 17 STATUS_CODE='S' rows.",
    ),
    ColumnSpec(
        "REMARKS",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS_EMBEDDED_PERSONAL,
        _C.EVIDENCED,
        "PNM's free-text operational history. Mined into core.remarks_signal.",
        "DEVIATION from the brief's personal-data list: 27,052 real values / 11,055 "
        "distinct, and they routinely name PMCare staff ('EMAIL AFIQ', 'AFIQAH 12022026'). "
        "Classed embedded-personal: usable by the miner, excluded from shareable views.",
    ),
    ColumnSpec(
        "CREATE_BY",
        _T.STRING,
        _D.PII,
        _P.PERSONAL,
        _C.EVIDENCED,
        "PMCare staff user ID that created the record.",
        "47 raw variants fold to 41 people.",
    ),
    ColumnSpec(
        "CREATE_DATE",
        _T.TIMESTAMP_MICROS,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "When PNM keyed the record. Not when the clinic opened.",
        "0 NULL.",
    ),
    ColumnSpec(
        "MODIFY_BY",
        _T.STRING,
        _D.PII,
        _P.PERSONAL,
        _C.EVIDENCED,
        "PMCare staff user ID that last modified the record.",
        "87 raw variants fold to 81 people.",
    ),
    ColumnSpec(
        "MODIFY_DATE",
        _T.TIMESTAMP_MICROS,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "When the record was last modified.",
        "11,139 NULL.",
    ),
    ColumnSpec(
        "ACC_VENDOR_FLAG",
        _T.BOOLEAN,
        _D.KEEP,
        _P.BUSINESS,
        _C.INFERRED,
        "Accounts-payable vendor flag.",
    ),
    ColumnSpec(
        "ACC_VENDOR_FLAG_DATE",
        _T.TIMESTAMP_MICROS,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Date the accounts vendor flag was set.",
        "Uses 1900-01-01 as a sentinel for 'not set' rather than NULL, in 12,877 rows "
        "(38%). Staging remaps the sentinel to NULL and logs the count.",
    ),
    ColumnSpec(
        "SYS_ISACTIVE",
        _T.BOOLEAN,
        _D.DROP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "System soft-delete flag.",
        "Dropped at staging: true in all 33,643 rows. Carries no signal and must not be "
        "confused with STATUS_CODE.",
    ),
    ColumnSpec(
        "SYS_ADMIN_REMARKS",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS_EMBEDDED_PERSONAL,
        _C.EVIDENCED,
        "System administrator free-text note.",
        "3,545 real values / 27 distinct. Free text by the same staff as REMARKS, so "
        "classed embedded-personal on the same basis.",
    ),
    ColumnSpec(
        "SYS_TIME_STAMP",
        _T.TIMESTAMP_MICROS,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "System row timestamp. Establishes extract vintage.",
        "0 NULL; max 2026-08-05 19:17:18.440.",
    ),
    ColumnSpec(
        "ROW_GUID",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Source row GUID. The second of only two safe keys.",
        "33,643/33,643 distinct.",
    ),
    ColumnSpec(
        "MIX_ROW_ID",
        _T.INT64,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Legacy integer row id. NOT a key.",
        "33,628 distinct — 15 rows collide in the range 16,170-16,192. Retained as a "
        "nullable, non-indexed passthrough. Never used in a join, index or constraint.",
    ),
    ColumnSpec(
        "isPMRused",
        _T.BOOLEAN,
        _D.KEEP,
        _P.BUSINESS,
        _C.INFERRED,
        "Whether the provider uses PMR.",
    ),
    ColumnSpec(
        "LATITUDE",
        _T.DOUBLE,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Latitude as keyed. Requires the coordinate gate before any use.",
        "17,525 NULL. Of 16,118 populated pairs only 9,878 are plausibly Malaysian; "
        "6,210 are exactly (0,0); max observed 932,799.",
    ),
    ColumnSpec(
        "LONGITUDE",
        _T.DOUBLE,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Longitude as keyed. Requires the coordinate gate before any use.",
        "17,525 NULL. Max observed 1.95670001957475e14.",
    ),
    ColumnSpec(
        "GST_REG_NO",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "GST registration number (GST was repealed in Malaysia in 2018).",
        "178 real values. Historical.",
    ),
    ColumnSpec(
        "GST_COMPANY_NAME",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Registered company name for GST purposes.",
        "583 real values.",
    ),
    ColumnSpec(
        "GST_COMPANY_REG_NO",
        _T.STRING,
        _D.PII,
        _P.PERSONAL,
        _C.EVIDENCED,
        "Company registration number. The only SSM-style identifier in PR001.",
        "125 real values (0.37%) but 18,164 non-NULL — 18,039 are blank strings. Values "
        "are inconsistent: genuine SSM numbers (202501030274), old-format (591650-X), "
        "and a company NAME ('JKLE SDN BHD'). There is effectively no SSM linkage here.",
    ),
    ColumnSpec(
        "STANDARD_HOUR_FROM",
        _T.TIME_NANOS,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Standard opening time.",
        "Populated for 836 rows (2.5%), using 00:00:00 as a placeholder within those.",
    ),
    ColumnSpec(
        "STANDARD_HOUR_TO",
        _T.TIME_NANOS,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Standard closing time.",
        "Populated for 836 rows (2.5%).",
    ),
    ColumnSpec(
        "PUBLIC_HOUR_FROM",
        _T.TIME_NANOS,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Public-holiday opening time.",
        "Populated for 836 rows (2.5%).",
    ),
    ColumnSpec(
        "PUBLIC_HOUR_TO",
        _T.TIME_NANOS,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Public-holiday closing time.",
        "Populated for 836 rows (2.5%).",
    ),
    ColumnSpec(
        "OWNERSHIP_CODE",
        _T.STRING,
        _D.KEEP,
        _P.BUSINESS,
        _C.UNKNOWN,
        "Unexplained ownership code. FK to ref_ownership.",
        "4 real codes: '0' 1,151 · '3' 55 · '2' 51 · '1' 43; 32,343 NULL. Meanings unknown.",
    ),
    ColumnSpec(
        "isAME",
        _T.BOOLEAN,
        _D.KEEP,
        _P.BUSINESS,
        _C.UNKNOWN,
        "Unexplained flag. Relationship to IsAME_MPM is unknown.",
    ),
    ColumnSpec(
        "isLTM",
        _T.BOOLEAN,
        _D.KEEP,
        _P.BUSINESS,
        _C.UNKNOWN,
        "Unexplained flag. The expansion of 'LTM' is unknown.",
    ),
    ColumnSpec(
        "IsEfarma",
        _T.BOOLEAN,
        _D.KEEP,
        _P.BUSINESS,
        _C.INFERRED,
        "Whether the provider participates in eFarma.",
    ),
    ColumnSpec(
        "NO_DOCTOR_MALE",
        _T.BOOLEAN,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Stored as BOOLEAN despite the name implying a count.",
        "Modelled as boolean, never integer. Whether a count was intended is an open question.",
    ),
    ColumnSpec(
        "NO_DOCTOR_FEMALE",
        _T.BOOLEAN,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Stored as BOOLEAN despite the name implying a count.",
        "Modelled as boolean, never integer.",
    ),
    ColumnSpec(
        "isPERKESO",
        _T.BOOLEAN,
        _D.KEEP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Whether the provider is on the PERKESO/SOCSO panel.",
        "True for only 114 rows — implausibly low against the real PERKESO panel. The "
        "field is under-maintained; do not use it as a PERKESO ground truth.",
    ),
    ColumnSpec(
        "isOH",
        _T.BOOLEAN,
        _D.KEEP,
        _P.BUSINESS,
        _C.UNKNOWN,
        "Unexplained flag, possibly occupational health.",
    ),
    ColumnSpec(
        "QR_ENCRYPTED_TEXT",
        _T.STRING,
        _D.QUARANTINE,
        _P.PERSONAL,
        _C.EVIDENCED,
        "Encrypted QR credential payload.",
        "QUARANTINED — a credential payload. Bronze only; never in an analytical or "
        "shareable layer, never in a fixture, never logged.",
    ),
    ColumnSpec(
        "QR_FILE_PATH",
        _T.STRING,
        _D.QUARANTINE,
        _P.BUSINESS,
        _C.EVIDENCED,
        "UNC path to the generated QR file.",
        "QUARANTINED — contains an internal server address (\\\\10.51.51.99\\LineDoc\\...). "
        "Infrastructure disclosure. Bronze only.",
    ),
    ColumnSpec(
        "APPS_PHONE_NO",
        _T.STRING,
        _D.PII,
        _P.PERSONAL,
        _C.EVIDENCED,
        "Phone number registered for the provider app.",
        "2,819 real values. Personal by guardrail 4.",
    ),
    ColumnSpec(
        "einv_tin_no",
        _T.STRING,
        _D.PII,
        _P.PERSONAL,
        _C.EVIDENCED,
        "LHDN e-invoicing tax identification number.",
        "4,017 real values. OG-prefixed values are individual/sole-proprietor TINs and so "
        "identify a natural person directly.",
    ),
    ColumnSpec(
        "einv_sst_no",
        _T.STRING,
        _D.PII,
        _P.PERSONAL,
        _C.EVIDENCED,
        "Sales & service tax number for e-invoicing.",
        "112 real values.",
    ),
    ColumnSpec(
        "einv_email",
        _T.STRING,
        _D.PII,
        _P.PERSONAL,
        _C.EVIDENCED,
        "E-invoicing contact email address.",
        "3,997 real values. Frequently a sole proprietor's personal mailbox, so this is "
        "not the clean 'business mailbox only' field the mockup assumed.",
    ),
    ColumnSpec(
        "id_LK180",
        _T.INT64,
        _D.KEEP,
        _P.BUSINESS,
        _C.UNKNOWN,
        "Unexplained lookup foreign key. FK to ref_lk180.",
        "4 real codes: 0 (1,867) · 3 (857) · 2 (120) · 1 (23); 30,776 NULL. Plain INT64, "
        "not a timestamp. What LK180 refers to is unknown.",
    ),
    ColumnSpec(
        "is_TwoStagesVerify",
        _T.BOOLEAN,
        _D.DROP,
        _P.BUSINESS,
        _C.EVIDENCED,
        "Two-stage verification flag.",
        "Dropped at staging: false in all 33,643 rows.",
    ),
    ColumnSpec(
        "IsAME_MPM",
        _T.BOOLEAN,
        _D.KEEP,
        _P.BUSINESS,
        _C.UNKNOWN,
        "Unexplained flag. Relationship to isAME is unknown.",
    ),
)

SOURCE_COLUMNS: Final[tuple[str, ...]] = tuple(c.name for c in SOURCE_COLUMN_SPECS)
"""All 70 source column names, in physical file order."""

SPEC_BY_NAME: Final[Mapping[str, ColumnSpec]] = {c.name: c for c in SOURCE_COLUMN_SPECS}

EXPECTED_ROW_COUNT: Final = 33_643
"""Row count of the 2026-08-05 extract. A future extract with fewer rows is source
shrinkage and must raise, never pass silently."""

DROPPED_AT_STAGING: Final[tuple[str, ...]] = tuple(
    c.name for c in SOURCE_COLUMN_SPECS if c.disposition is Disposition.DROP
)
QUARANTINED: Final[tuple[str, ...]] = tuple(
    c.name for c in SOURCE_COLUMN_SPECS if c.disposition is Disposition.QUARANTINE
)
PERSONAL_DATA_COLUMNS: Final[tuple[str, ...]] = tuple(
    c.name for c in SOURCE_COLUMN_SPECS if c.pdpa_class is PdpaClass.PERSONAL
)
RESTRICTED_COLUMNS: Final[frozenset[str]] = frozenset(
    c.name for c in SOURCE_COLUMN_SPECS if c.restricted
)
"""Columns that must never appear in a shareable view, a fixture, or a log line."""

USER_ID_COLUMNS: Final[tuple[str, ...]] = (
    "GL_ELIGIBILITY_APPROVE_BY",
    "STATUS_BY",
    "CREATE_BY",
    "MODIFY_BY",
)
"""Staff user-ID columns. Case-folded into ref_user; the same person appears as both
M_NOOR and m_noor."""

TIMESTAMP_COLUMNS: Final[tuple[str, ...]] = tuple(
    c.name for c in SOURCE_COLUMN_SPECS if c.logical_type is LogicalType.TIMESTAMP_MICROS
)
TIME_COLUMNS: Final[tuple[str, ...]] = tuple(
    c.name for c in SOURCE_COLUMN_SPECS if c.logical_type is LogicalType.TIME_NANOS
)

BRONZE_AUDIT_COLUMNS: Final[tuple[str, ...]] = (
    "_ingest_id",
    "_ingested_at",
    "_source_filename",
    "_source_sha256",
    "_row_ordinal",
)

ACC_VENDOR_FLAG_SENTINEL_YEAR: Final = 1900
"""ACC_VENDOR_FLAG_DATE uses 1900-01-01 to mean 'not set' rather than NULL."""


def is_restricted(column: str) -> bool:
    """Whether `column` is barred from shareable views, fixtures and logs.

    Unknown column names are treated as restricted — failing closed is the only safe
    default for a PDPA control.
    """
    spec = SPEC_BY_NAME.get(column)
    return True if spec is None else spec.restricted
