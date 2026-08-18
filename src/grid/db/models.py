"""SQLAlchemy table definitions for GRID's layered model.

Layers, and the rule each enforces:

* **bronze** — what the source said. Verbatim, append-only generations, no coercion.
* **staging** — what the source said, typed and cleaned. One row per bronze row of the
  current generation. Reference tables live here too.
* **core** — what we concluded. The incumbent network, discovery candidates, and the
  resolution edges between them.
* **ops** — what happened during a load. Counts, thresholds, drift.
* **pii** — personal data under PDPA 2010, segregated at schema level (guardrail 4).

Designed in `docs/context/data-model.md`; the rationale for the two restructures against
the original mockup is in `docs/reconciliation-pr001.md` §5 and ADR 0005.
"""

from __future__ import annotations

import datetime as dt
from typing import Final

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from grid.pr001.columns import SOURCE_COLUMN_SPECS, LogicalType

NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all GRID tables."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# --------------------------------------------------------------------------------------
# bronze — source landing
# --------------------------------------------------------------------------------------

_SQL_TYPE_FOR = {
    LogicalType.STRING: Text,
    LogicalType.BOOLEAN: Boolean,
    LogicalType.INT64: BigInteger,
    LogicalType.DOUBLE: Float,
    LogicalType.TIMESTAMP_MICROS: DateTime,
    LogicalType.TIME_NANOS: Time,
}


def _bronze_source_columns() -> list[Column[object]]:
    """Build the 70 source columns from the contract, preserving names and order.

    Generated rather than hand-listed so bronze cannot drift from
    `grid.pr001.columns.SOURCE_COLUMN_SPECS`. Every column is nullable — bronze accepts
    whatever the file holds, including values that violate every expectation we have.
    """
    return [
        Column(spec.name, _SQL_TYPE_FOR[spec.logical_type](), nullable=True)
        for spec in SOURCE_COLUMN_SPECS
    ]


pr001_provider_master = Table(
    "pr001_provider_master",
    Base.metadata,
    # Audit columns. Underscore-prefixed to keep them unmistakably ours, never the
    # source's — PR001 has no underscore-prefixed column of its own.
    Column("_ingest_id", String(36), nullable=False, primary_key=True),
    Column("_row_ordinal", BigInteger, nullable=False, primary_key=True),
    Column("_ingested_at", DateTime, nullable=False),
    Column("_source_filename", Text, nullable=False),
    Column("_source_sha256", String(64), nullable=False),
    *_bronze_source_columns(),
    Index("ix_bronze_pr001_sha256", "_source_sha256"),
    Index("ix_bronze_pr001_provider_code", "PROVIDER_CODE"),
    schema="bronze",
    comment=(
        "PMCare incumbent provider master, verbatim. Append-only generations keyed by "
        "_ingest_id; idempotent on _source_sha256. Contains personal data and the "
        "quarantined QR_* columns — never selected wholesale outside the loader."
    ),
)
"""All 70 source columns with original names and types, plus five audit columns.

`_row_ordinal` records position in the source file because PR001 has no meaningful sort
order; it makes a reload byte-comparable against a prior generation.
"""


class BronzeGeneration(Base):
    """One load of one file. The idempotency ledger for bronze."""

    __tablename__ = "pr001_generation"
    __table_args__ = (
        UniqueConstraint("source_sha256", name="uq_pr001_generation_source_sha256"),
        {"schema": "bronze"},
    )

    ingest_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_filename: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ingested_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# --------------------------------------------------------------------------------------
# staging — reference tables
# --------------------------------------------------------------------------------------

_REF_COMMENT = (
    "Seeded only from what the data evidences. `meaning` stays NULL and `source` stays "
    "'unknown' where we do not know — a documented NULL beats a plausible guess."
)


class _RefMixin:
    """Shared shape for every code reference table."""

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    meaning: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


_REF_SOURCE_CK = "source IN ('confirmed_by_pnm', 'inferred', 'unknown')"


def _ref_args(table: str) -> tuple[object, ...]:
    return (
        CheckConstraint(_REF_SOURCE_CK, name="source_enum"),
        {"schema": "staging", "comment": f"{table}: {_REF_COMMENT}"},
    )


class RefProviderType(_RefMixin, Base):
    """PROVIDER_TYPE_CODE — 21 codes, 7 inferred, 14 unknown."""

    __tablename__ = "ref_provider_type"
    __table_args__ = _ref_args("ref_provider_type")


class RefState(_RefMixin, Base):
    """STATE_CODE — 15 plausible states/FTs, plus PJ (inferred), ZZ and 00 (unknown)."""

    __tablename__ = "ref_state"
    __table_args__ = _ref_args("ref_state")


class RefStatus(_RefMixin, Base):
    """STATUS_CODE — A/T/S evidenced by cross-field date consistency; V unknown."""

    __tablename__ = "ref_status"
    __table_args__ = _ref_args("ref_status")


class RefCategory(_RefMixin, Base):
    """CATEGORY_CODE — codes only, all meanings unknown."""

    __tablename__ = "ref_category"
    __table_args__ = _ref_args("ref_category")


class RefPaymentMethod(_RefMixin, Base):
    """PAYMENT_METHOD_CODE — codes only, all meanings unknown."""

    __tablename__ = "ref_payment_method"
    __table_args__ = _ref_args("ref_payment_method")


class RefOwnership(_RefMixin, Base):
    """OWNERSHIP_CODE — codes only, all meanings unknown."""

    __tablename__ = "ref_ownership"
    __table_args__ = _ref_args("ref_ownership")


class RefLk180(_RefMixin, Base):
    """id_LK180 — codes only, all meanings unknown. What LK180 refers to is unknown."""

    __tablename__ = "ref_lk180"
    __table_args__ = _ref_args("ref_lk180")


class RefUser(Base):
    """Canonical PMCare staff identity, case-folded.

    PR001 stores the same person in mixed case across four columns — `M_NOOR` and
    `m_noor` are one user. The canonical form is lowercase; every raw variant seen is
    retained so an audit can trace back to the source spelling.

    Staff user IDs are personal data. This table is a lookup, not an analytical
    dimension, and is excluded from shareable views.
    """

    __tablename__ = "ref_user"
    __table_args__ = ({"schema": "staging"},)

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    raw_variants: Mapped[str] = mapped_column(Text, nullable=False)
    seen_in_columns: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_ingest_id: Mapped[str] = mapped_column(String(36), nullable=False)


class RefCity(Base):
    """Canonicalised city, keyed on (city_raw, postcode_prefix).

    CITY is free text with 1,019 distinct values and no controlled vocabulary. Seeded
    from the data; unmatched values are flagged rather than guessed.
    """

    __tablename__ = "ref_city"
    __table_args__ = (
        CheckConstraint(_REF_SOURCE_CK, name="source_enum"),
        {"schema": "staging"},
    )

    city_raw: Mapped[str] = mapped_column(Text, primary_key=True)
    postcode_prefix: Mapped[str] = mapped_column(String(2), primary_key=True)
    city_canonical: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class RefPostcodePrefixState(Base):
    """Empirical postcode-prefix to state mapping, derived from PR001 itself.

    Open question 12 forbids coding a postcode-to-state table "from folklore ranges",
    and the authoritative Pos Malaysia-derived dataset is unresolved. So this table is
    derived from the observed distribution in the extract and marked `inferred` — it
    supports a mismatch *flag*, never an overwrite of either field.
    """

    __tablename__ = "ref_postcode_prefix_state"
    __table_args__ = (
        CheckConstraint(_REF_SOURCE_CK, name="source_enum"),
        {"schema": "staging"},
    )

    postcode_prefix: Mapped[str] = mapped_column(String(2), primary_key=True)
    modal_state_code: Mapped[str] = mapped_column(Text, nullable=False)
    modal_share: Mapped[float] = mapped_column(Float, nullable=False)
    observation_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="inferred")


# --------------------------------------------------------------------------------------
# staging — the typed outlet row
# --------------------------------------------------------------------------------------


class StagingProviderOutlet(Base):
    """One row per bronze row of the current generation. 33,643 rows.

    `provider_code` and `row_guid` both carry unique constraints — they are the only two
    safe keys. `mix_row_id` is retained as a nullable, non-indexed passthrough with no
    constraint of any kind.
    """

    __tablename__ = "provider_outlet"
    __table_args__ = (
        UniqueConstraint("provider_code", name="uq_provider_outlet_provider_code"),
        UniqueConstraint("row_guid", name="uq_provider_outlet_row_guid"),
        CheckConstraint(
            "coord_quality IN ('VALID','MISSING','NULL_ISLAND','OUT_OF_BOUNDS',"
            "'REPAIRED_DECIMAL','REPAIRED_SPLIT')",
            name="coord_quality_enum",
        ),
        Index("ix_staging_outlet_blocking", "name_normalised", "postcode_clean"),
        Index("ix_staging_outlet_type_status", "provider_type_code", "status_code"),
        {"schema": "staging"},
    )

    provider_code: Mapped[str] = mapped_column(Text, primary_key=True)
    row_guid: Mapped[str] = mapped_column(Text, nullable=False)
    ingest_id: Mapped[str] = mapped_column(String(36), nullable=False)
    row_ordinal: Mapped[int] = mapped_column(BigInteger, nullable=False)

    mix_row_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment=(
            "NOT A KEY. 15 rows collide in the source range 16,170-16,192. Deliberately "
            "unindexed and unconstrained; never use in a join."
        ),
    )

    # Classification codes — every one an FK into a reference table, so an unseen code
    # breaks the build rather than flowing through as NULL.
    provider_type_code: Mapped[str] = mapped_column(
        ForeignKey("staging.ref_provider_type.code"), nullable=False
    )
    category_code: Mapped[str] = mapped_column(
        ForeignKey("staging.ref_category.code"), nullable=False
    )
    payment_method_code: Mapped[str] = mapped_column(
        ForeignKey("staging.ref_payment_method.code"), nullable=False
    )
    status_code: Mapped[str] = mapped_column(ForeignKey("staging.ref_status.code"), nullable=False)
    state_code: Mapped[str] = mapped_column(ForeignKey("staging.ref_state.code"), nullable=False)
    ownership_code: Mapped[str | None] = mapped_column(
        ForeignKey("staging.ref_ownership.code"), nullable=True
    )
    lk180_code: Mapped[str | None] = mapped_column(
        ForeignKey("staging.ref_lk180.code"), nullable=True
    )

    # Names
    name_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_normalised: Mapped[str | None] = mapped_column(Text, nullable=True)
    chain_base_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch_qualifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch_qualifier_expanded: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Addresses — raw lines always retained
    address1_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    address2_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    address3_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_street: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_locality: Mapped[str | None] = mapped_column(Text, nullable=True)

    city_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    city_canonical: Mapped[str | None] = mapped_column(Text, nullable=True)
    city_unmatched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    postcode_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    postcode_clean: Mapped[str | None] = mapped_column(String(5), nullable=True)
    postcode_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    postcode_state_mismatch: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        comment=(
            "True where the postcode's modal state disagrees with state_code. The "
            "postcode is treated as the more reliable of the two, but NEITHER field is "
            "overwritten. NULL where the prefix has no empirical mapping."
        ),
    )

    # Coordinates — see grid.normalise.coordinates
    latitude_raw: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude_raw: Mapped[float | None] = mapped_column(Float, nullable=True)
    latitude_clean: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude_clean: Mapped[float | None] = mapped_column(Float, nullable=True)
    coord_quality: Mapped[str] = mapped_column(Text, nullable=False)
    coord_repair_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status and lifecycle
    pmcare_panel_status: Mapped[bool] = mapped_column(Boolean, nullable=False)
    appointment_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    termination_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    suspension_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    status_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    create_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    modify_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    sys_time_stamp: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    acc_vendor_flag_date: Mapped[dt.datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="Source sentinel 1900-01-01 ('not set') remapped to NULL; count logged.",
    )

    # Operating hours — unset when all four source columns read 00:00:00
    standard_hour_from: Mapped[dt.time | None] = mapped_column(Time, nullable=True)
    standard_hour_to: Mapped[dt.time | None] = mapped_column(Time, nullable=True)
    public_hour_from: Mapped[dt.time | None] = mapped_column(Time, nullable=True)
    public_hour_to: Mapped[dt.time | None] = mapped_column(Time, nullable=True)
    operating_hours_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Staff attribution — canonical, case-folded
    status_by: Mapped[str | None] = mapped_column(
        ForeignKey("staging.ref_user.user_id"), nullable=True
    )
    create_by: Mapped[str | None] = mapped_column(
        ForeignKey("staging.ref_user.user_id"), nullable=True
    )
    modify_by: Mapped[str | None] = mapped_column(
        ForeignKey("staging.ref_user.user_id"), nullable=True
    )
    gl_eligibility_approve_by: Mapped[str | None] = mapped_column(
        ForeignKey("staging.ref_user.user_id"), nullable=True
    )

    # Remaining business flags, carried through unchanged
    mediline_user: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    open_24_hours: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    open_public_holidays: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gl_eligibility_status: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    acc_vendor_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_pmr_used: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_ame: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_ame_mpm: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_ltm: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_efarma: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_perkeso: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        comment="True for only 114 rows — under-maintained. Not a PERKESO ground truth.",
    )
    is_oh: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    no_doctor_male: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="BOOLEAN in source despite the name. Never an integer."
    )
    no_doctor_female: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    general_fax_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    gst_reg_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    gst_company_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Free text with embedded personal data — excluded from shareable views
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    sys_admin_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)


# --------------------------------------------------------------------------------------
# core — the modelled network
# --------------------------------------------------------------------------------------


class CoreProviderOutlet(Base):
    """The incumbent network. Sourced only from staging.

    This is the reconciliation target for discovery. **GRID must never write candidate
    rows into it** — discovered clinics live in `core.grid_candidate` until a resolution
    decision promotes them, and even then the promotion is a link, not a row copy.
    """

    __tablename__ = "provider_outlet"
    __table_args__ = (
        UniqueConstraint("row_guid", name="uq_core_provider_outlet_row_guid"),
        CheckConstraint(
            "coord_quality IN ('VALID','MISSING','NULL_ISLAND','OUT_OF_BOUNDS',"
            "'REPAIRED_DECIMAL','REPAIRED_SPLIT')",
            name="coord_quality_enum",
        ),
        Index("ix_core_outlet_blocking", "name_normalised", "postcode_clean"),
        Index("ix_core_outlet_chain", "chain_base_name"),
        {"schema": "core", "comment": "Incumbent network from PR001. Never written by discovery."},
    )

    provider_code: Mapped[str] = mapped_column(Text, primary_key=True)
    row_guid: Mapped[str] = mapped_column(Text, nullable=False)

    name_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_normalised: Mapped[str | None] = mapped_column(Text, nullable=True)
    chain_base_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch_qualifier: Mapped[str | None] = mapped_column(Text, nullable=True)

    address_unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_street: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_locality: Mapped[str | None] = mapped_column(Text, nullable=True)
    city_canonical: Mapped[str | None] = mapped_column(Text, nullable=True)
    postcode_clean: Mapped[str | None] = mapped_column(String(5), nullable=True)
    postcode_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state_code: Mapped[str] = mapped_column(Text, nullable=False)
    postcode_state_mismatch: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    latitude_clean: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude_clean: Mapped[float | None] = mapped_column(Float, nullable=True)
    coord_quality: Mapped[str] = mapped_column(Text, nullable=False)

    provider_type_code: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[str] = mapped_column(Text, nullable=False)
    pmcare_panel_status: Mapped[bool] = mapped_column(Boolean, nullable=False)
    appointment_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    termination_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    suspension_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    operating_hours_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    sourced_from_ingest_id: Mapped[str] = mapped_column(String(36), nullable=False)


class CoreChain(Base):
    """A multi-outlet brand, derived from `chain_base_name`.

    Chain membership is **inferred, not fact** — 3,303 name groups cover 10,426 rows and
    a shared name can mean a genuine chain or a re-keyed duplicate. Every membership
    carries a confidence value and the outlets stay separate rows.
    """

    __tablename__ = "chain"
    __table_args__ = (
        UniqueConstraint("chain_base_name", name="uq_chain_chain_base_name"),
        {"schema": "core"},
    )

    chain_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chain_base_name: Mapped[str] = mapped_column(Text, nullable=False)
    outlet_count: Mapped[int] = mapped_column(Integer, nullable=False)
    name_variants: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="inferred")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class CoreOutletChainMember(Base):
    """Edge from an outlet to an inferred chain, with a confidence value."""

    __tablename__ = "outlet_chain_member"
    __table_args__ = (
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="confidence_range"),
        {"schema": "core"},
    )

    provider_code: Mapped[str] = mapped_column(
        ForeignKey("core.provider_outlet.provider_code"), primary_key=True
    )
    chain_id: Mapped[str] = mapped_column(ForeignKey("core.chain.chain_id"), primary_key=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)


class CoreGridCandidate(Base):
    """A clinic discovered from an external source, not yet reconciled to the network.

    Mirrors the useful subset of the outlet shape — including the *same* `coord_quality`
    enum — so a candidate and an incumbent are directly comparable field for field.
    """

    __tablename__ = "grid_candidate"
    __table_args__ = (
        UniqueConstraint("source_key", "source_natural_id", name="uq_grid_candidate_source"),
        CheckConstraint(
            "coord_quality IN ('VALID','MISSING','NULL_ISLAND','OUT_OF_BOUNDS',"
            "'REPAIRED_DECIMAL','REPAIRED_SPLIT')",
            name="coord_quality_enum",
        ),
        Index("ix_candidate_blocking", "name_normalised", "postcode_clean"),
        {"schema": "core"},
    )

    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_natural_id: Mapped[str] = mapped_column(Text, nullable=False)

    name_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_normalised: Mapped[str | None] = mapped_column(Text, nullable=True)
    chain_base_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch_qualifier: Mapped[str | None] = mapped_column(Text, nullable=True)

    address_unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_street: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_locality: Mapped[str | None] = mapped_column(Text, nullable=True)
    city_canonical: Mapped[str | None] = mapped_column(Text, nullable=True)
    postcode_clean: Mapped[str | None] = mapped_column(String(5), nullable=True)
    postcode_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state_code: Mapped[str | None] = mapped_column(Text, nullable=True)

    latitude_clean: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude_clean: Mapped[float | None] = mapped_column(Float, nullable=True)
    coord_quality: Mapped[str] = mapped_column(Text, nullable=False)

    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)


class CoreOutletCandidateLink(Base):
    """The resolution edge between a discovery candidate and an incumbent outlet.

    Human decisions are immutable and always override algorithmic ones: a row whose
    `decision` is `human_confirmed_match` or `human_confirmed_new` must never be
    rewritten by the matcher. Enforced in `grid.resolve` and asserted in tests.
    """

    __tablename__ = "outlet_candidate_link"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('auto_match','auto_new','review_queue',"
            "'human_confirmed_match','human_confirmed_new')",
            name="decision_enum",
        ),
        CheckConstraint("match_score >= 0.0 AND match_score <= 1.0", name="match_score_range"),
        UniqueConstraint("candidate_id", "provider_code", name="uq_link_candidate_provider"),
        Index("ix_link_decision", "decision"),
        {"schema": "core"},
    )

    link_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("core.grid_candidate.candidate_id"), nullable=False
    )
    provider_code: Mapped[str | None] = mapped_column(
        ForeignKey("core.provider_outlet.provider_code"), nullable=True
    )
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    match_method: Mapped[str] = mapped_column(Text, nullable=False)
    blocking_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class CoreRemarksSignal(Base):
    """A structured signal mined from PNM's free-text REMARKS.

    `raw_fragment` is mandatory: every extraction must be auditable by a human back to
    the text that produced it. Precision over recall — an unmatched remark is fine, a
    wrong edge is not.
    """

    __tablename__ = "remarks_signal"
    __table_args__ = (
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="confidence_range"),
        Index("ix_remarks_signal_type", "signal_type"),
        {"schema": "core"},
    )

    signal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_code: Mapped[str] = mapped_column(Text, nullable=False)
    signal_type: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_fragment: Mapped[str] = mapped_column(Text, nullable=False)
    pattern_id: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class CoreProviderCodeSupersession(Base):
    """Directed edge: `superseded_code` was replaced by `superseding_code`.

    Mined from REMARKS — PNM telling us which records are the same clinic. Both endpoints
    must resolve to a real PROVIDER_CODE before an edge is emitted. The graph may contain
    cycles; consumers must handle them rather than assume a DAG.
    """

    __tablename__ = "provider_code_supersession"
    __table_args__ = (
        UniqueConstraint("superseded_code", "superseding_code", name="uq_supersession_pair"),
        CheckConstraint("superseded_code <> superseding_code", name="no_self_edge"),
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="confidence_range"),
        {"schema": "core"},
    )

    superseded_code: Mapped[str] = mapped_column(Text, primary_key=True)
    superseding_code: Mapped[str] = mapped_column(Text, primary_key=True)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    pattern_id: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


# --------------------------------------------------------------------------------------
# pii — personal data, segregated at schema level (guardrail 4)
# --------------------------------------------------------------------------------------


class PiiProviderContact(Base):
    """Personal data extracted from PR001, keyed on provider_code.

    Segregated from business data at schema level per PDPA 2010 (as amended 2024) and
    guardrail 4. A sole proprietor's dual-use mobile is personal data, so no attempt is
    made to split "clinic line" from "personal line" — the whole column is personal.

    `doctor_name` is available downstream **only** as `doctor_name_hash`, a salted hash
    for matching. The plaintext column is access-controlled and the salt lives outside
    the repository (`GRID_PII_HASH_SALT`).

    Every row records `lawful_basis` and `retention_until` at write time, matching the
    `practitioner` contract in `docs/context/data-model.md`.
    """

    __tablename__ = "provider_contact"
    __table_args__ = (
        {"schema": "pii", "comment": "PERSONAL DATA — never in a shareable view or fixture."},
    )

    provider_code: Mapped[str] = mapped_column(Text, primary_key=True)
    doctor_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    doctor_name_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    general_phone_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    apps_phone_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    einv_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    einv_tin_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    einv_sst_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    hbrn: Mapped[str | None] = mapped_column(Text, nullable=True)
    gst_company_reg_no: Mapped[str | None] = mapped_column(Text, nullable=True)

    lawful_basis: Mapped[str] = mapped_column(Text, nullable=False)
    retention_until: Mapped[dt.date] = mapped_column(Date, nullable=False)
    purpose_note: Mapped[str] = mapped_column(Text, nullable=False)
    source_key: Mapped[str] = mapped_column(Text, nullable=False, default="pr001")


# --------------------------------------------------------------------------------------
# ops — load and transform accounting
# --------------------------------------------------------------------------------------


class OpsLoadLog(Base):
    """One row per load attempt, whatever the outcome."""

    __tablename__ = "load_log"
    __table_args__ = ({"schema": "ops"},)

    load_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ingest_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    layer: Mapped[str] = mapped_column(Text, nullable=False)
    source_filename: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rows_in: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rows_out: Mapped[int] = mapped_column(BigInteger, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class OpsTransformLog(Base):
    """One row per named transform per load. Counts are the audit trail.

    A transform that changes more rows than its configured threshold raises rather than
    proceeds — silent mass mutation is the failure mode this table exists to catch.
    """

    __tablename__ = "transform_log"
    __table_args__ = (
        ForeignKeyConstraint(["load_id"], ["ops.load_log.load_id"], name="fk_transform_load"),
        Index("ix_transform_log_load", "load_id"),
        {"schema": "ops"},
    )

    transform_log_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    load_id: Mapped[str] = mapped_column(String(36), nullable=False)
    transform_name: Mapped[str] = mapped_column(Text, nullable=False)
    rows_considered: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rows_changed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    breached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
