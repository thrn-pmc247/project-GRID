---
title: Data Model
owner: thiran
last_verified: 2026-08-17
verify_by: 2026-11-15
covers_paths:
  - src/grid/db/**
  - src/grid/pr001/**
status: current
---

# Data model

Four layers, expressed as real SQL schemas: **`bronze`** (source verbatim),
**`staging`** (conformed + reference data), **`core`** (analytical, shareable),
**`ops`** (run logs), **`pii`** (segregated personal data). Postgres in production;
offline and in tests, SQLite with `ATTACH DATABASE` per schema — ADR 0006.

Every column carries a `pdpa_class`: `business` (default, low risk), `personal` (full
PDPA regime — restricted schema, lawful basis, retention, purpose; never in default API
responses), or `business_embedded_personal` (nominally business free text that
demonstrably names individuals — usable inside the pipeline, excluded from shareable
views). A sole proprietor's mobile that doubles as the clinic line is **personal**.
Unless a table says otherwise below, all its columns are `business`.

The incumbent side of this model is fixed by **ADR 0005** and evidenced column by column
in **`docs/reconciliation-pr001.md`**. The per-column contract lives in
`src/grid/pr001/columns.py`; `docs/data-dictionary-pr001.yaml` is generated from it by
`tools/generate_data_dictionary.py` and is never hand-edited.

## Shared enums

`coord_quality` — on **both** `core.provider_outlet` and `core.grid_candidate`, so the
two stay comparable field-for-field:

`VALID` · `MISSING` (either component NULL) · `NULL_ISLAND` (exactly 0, 0) ·
`OUT_OF_BOUNDS` · `REPAIRED_DECIMAL` · `REPAIRED_SPLIT`

Coordinates are **confirmatory only** in resolution, read solely when
`coord_quality = 'VALID'` on both sides. Only 9,878 of 33,643 incumbent rows (29.4%)
qualify, which is why blocking is `name_normalised + postcode` (ADR 0005).

`link_decision` — on `core.outlet_candidate_link`:

`auto_match` · `auto_new` · `review_queue` · `human_confirmed_match` ·
`human_confirmed_new`

The two `human_confirmed_*` values are **immutable and always override** any algorithmic
value. A re-run may add rows; it may never rewrite a human decision.

## `bronze.pr001_provider_master`

70 source columns **verbatim**, unmodified and untyped-down, plus five audit columns:
`_ingest_id`, `_ingested_at`, `_source_filename`, `_source_sha256`, `_row_ordinal`.

- **Append-only generations.** A reload adds a new `_ingest_id` generation; nothing is
  updated in place.
- **Idempotent on `_source_sha256`.** Re-ingesting the same file is a no-op, logged.
- `_row_ordinal` preserves physical file order, so a bronze row is reproducible from the
  source file alone.
- This is the **only** layer that may hold the quarantined columns
  `QR_ENCRYPTED_TEXT` (`personal` — a credential payload) and `QR_FILE_PATH` (contains
  an internal file-server path). Never selected into staging, a fixture, or a log line.
- The 12 `personal` and 3 `business_embedded_personal` columns land here as they arrive;
  segregation happens at the staging boundary.

## `staging` — reference tables

Nine lookups, each with `code`, `label`, and `source ∈ {confirmed_by_pnm, inferred,
unknown}`. `unknown` is a legitimate, expected state — see `open-questions.md`.

| Table | Seeded from | State |
|---|---|---|
| `ref_provider_type` | `PROVIDER_TYPE_CODE`, 21 codes | 7 resolved, **14 unknown** |
| `ref_state` | `STATE_CODE`, 18 codes | 15 plausible; `PJ` inferred, `ZZ`/`00` unknown |
| `ref_status` | `STATUS_CODE`, 4 codes | A/T/S confirmed by cross-field consistency; `V` unknown |
| `ref_category` | `CATEGORY_CODE`, 7 codes | all **unknown** |
| `ref_payment_method` | `PAYMENT_METHOD_CODE`, 3 codes | all **unknown** |
| `ref_ownership` | `OWNERSHIP_CODE`, 4 codes | all **unknown** |
| `ref_lk180` | `id_LK180`, 4 codes | all **unknown** |
| `ref_user` | the 4 staff user-ID columns | **`personal`** — lives in `pii`-equivalent access control; canonical lowercase key, raw variants retained |
| `ref_city` | `CITY`, 1,019 distinct free-text values | canonicalisation target, no controlled vocabulary upstream |

`state_code` is a **FK to `ref_state`, never a closed enum** — a 16-value enum would
reject 148 real rows.

## `staging.provider_outlet`

33,643 rows conformed from bronze. `UNIQUE(provider_code)`, `UNIQUE(row_guid)` — the
only two safe keys (33,643/33,643 distinct each).

`mix_row_id` is a **nullable, non-indexed passthrough with no constraint**. 33,628
distinct; 15 rows collide. It must never appear in a join, an index or a constraint.

At this boundary the pipeline: drops the five no-information columns; refuses to select
the two quarantined ones; routes `personal` columns to `pii.provider_contact`; remaps
the `ACC_VENDOR_FLAG_DATE` sentinel year 1900 to NULL **and logs the count** (12,877
rows); stores `postcode` as `text` with a validity flag and a `postcode_state_mismatch`
flag, never coerced to `char(5)`; and computes `coord_quality`.

Address arrives as three free-text lines (`address1`, `address2`, `address3`) — there is
no single canonical address field upstream and no `district` column at all.

## `core.provider_outlet` — the incumbent network

The clinics PMCare already has. Written **from `staging` only**. GRID must never write a
candidate row into this table.

| Column | Type | Notes |
|---|---|---|
| `provider_code` | text PK | business key, carried through every layer |
| `row_guid` | text UNIQUE | source row identity |
| `name_raw`, `name_normalised` | text | corporate suffix and parenthesised branch qualifier stripped before grouping |
| `name_variants` | text[] | every observed spelling |
| `address1..3`, `city_id` FK, `postcode`, `postcode_valid`, `state_code` FK | | `city_id` → `ref_city`, `state_code` → `ref_state` |
| `latitude`, `longitude` | double precision, nullable | plain floats, not PostGIS — ADR 0006 |
| `coord_quality` | enum | gate for any coordinate use |
| `provider_type_code` FK, `category_code` FK, `payment_method_code` FK, `ownership_code` FK, `lk180_code` FK | | four of the five have **unknown** meanings |
| `pmcare_panel_status` | boolean | **authoritative** for suppression (GP + status `A` + panel = 5,956) |
| `status_code` FK, `status_date`, `termination_date`, `suspension_date` | | see the point-in-time rule below |
| `appointment_date` | timestamptz | panel appointment, **not** facility registration. 0 NULL; 1995-05-02 to 2026-08-05 |
| `create_date`, `modify_date`, `sys_time_stamp` | timestamptz | `create_date` is when PNM keyed the record, not when the clinic opened |
| operating flags and hours | boolean / time | `open24hours`, `open_public_holidays`, standard and public-holiday hours (populated for 836 rows, 2.5%) |
| `no_doctor_male`, `no_doctor_female` | **boolean** | stored as boolean despite count-like names — modelled as boolean, never integer |
| `_ingest_id` | FK → `ops.load_log` | provenance |

**Point-in-time status.** `termination_date` reaches 2028-08-05, so `active` is
**never** `termination_date IS NULL`. It is a point-in-time function evaluated against
an as-at date; re-running a historical month with a NULL test silently returns the wrong
answer. One row is future-dated today, and the trap grows.

## `core.chain` and `core.outlet_chain_member`

`chain` — `chain_id`, `chain_name_normalised`, `outlet_count`.
`outlet_chain_member` — `chain_id` FK, `provider_code` FK, `confidence` float,
`method`, `inferred_at`.

Chain membership is **inferred, always with a confidence**, never asserted. 3,303 name
groups cover 10,426 rows (31%), and those groups mix genuine multi-outlet chains — which
must remain separate rows — with the same premises keyed twice. Chain inference never
gates suppression on its own.

## `core.grid_candidate` — discovered clinics

Mirrors the `core.provider_outlet` field shape, including the same `coord_quality` enum,
plus discovery-side columns:

`candidate_id` UUID PK · `source_key` · `source_natural_id` (the per-source natural key,
e.g. MyGeoCKAPS `ID_UNIK_PHS` — field name unconfirmed, open q. 14) ·
`status_operasi` (operational status as published, if present) · `google_place_id`
(**the only Places content persisted**) · `first_seen_at` · `registered_at`
(NULL unless the source exposes one — open q. 14) · `opened_estimate` ·
`opened_confidence` · `scope` (`gp` | `gp_with_interest` | `specialist` | `excluded`).

> **If `registered_at` cannot be sourced**, GRID's clock starts at the first snapshot:
> for the first few months a genuinely new clinic is indistinguishable from one newly
> added to the GIS. Queue A then rests entirely on `recency_signal` corroboration and
> Queue B carries the KPI. This remains the highest-consequence open item in the project.

## `core.outlet_candidate_link` — the resolution edge

`candidate_id` FK · `provider_code` FK · `match_score` float · `match_method` ·
`blocking_key` · `decision` (`link_decision` enum) · `decided_by` · `decided_at`.

One row per resolution decision, retained. `blocking_key` records **which** block
produced the pair, so recall failures are diagnosable rather than invisible. Human
decisions are immutable and always override algorithmic ones.

## `core.remarks_signal` and `core.provider_code_supersession`

`remarks_signal` — `provider_code` FK, `signal_type`, `matched_fragment`,
`extracted_at`. `pdpa_class: business_embedded_personal`, because `REMARKS` (27,052 real
values) routinely names PMCare staff. Excluded from shareable views; available to the
miner. Evidenced signal types include `DUPLICATE` (356) and `CLOSED` (537).

`provider_code_supersession` — `from_provider_code`, `to_provider_code`, `evidence`,
`confidence`, a directed graph of code changes. An edge is emitted **only** when the
target token exists in the 33,643-code universe *and* a supersession keyword appears in
the fragment. A naive `CHANGE TO (\S+)` regex resolves 1 of 167 matches; precision over
recall, deliberately.

## `core.v_kpi_appointments_monthly`

View over `core.provider_outlet.appointment_date`. GP series separable via
`provider_type_code`; excludes superseded codes. Supplies the historical baseline
`kpi_month` is measured against.

## `ops.load_log` and `ops.transform_log`

`load_log` — `_ingest_id` PK, `source_filename`, `source_sha256`, `row_count`,
`started_at`, `finished_at`, `status`.
`transform_log` — `_ingest_id` FK, `step`, `rule`, `rows_in`, `rows_out`,
`rows_changed`, `detail`.

Every sentinel remap, drop and quarantine writes a counted row. A threshold breach
**raises** — a source returning zero rows is a failure, not an empty success.

## `pii.provider_contact` — PERSONAL DATA, restricted access

`provider_code` FK · `general_phone_no` · `apps_phone_no` · `einv_email` ·
`einv_tin_no` · `einv_sst_no` · `gst_company_reg_no` · `hbrn` · `doctor_name_hash` ·
`lawful_basis` NOT NULL · `retention_until` NOT NULL · `purpose_note` · `source_key`.

All columns `personal`. Excluded from every default analytical view and from API
responses. `doctor_name` is available downstream **only as a salted hash**; plaintext is
access-controlled and the salt lives outside the repo. `hbrn` is treated as personal
until confirmed, since a sole proprietor's registration identifies an individual.

## Entities carried over from the discovery design

### `clinic_source_record` — provenance (business; `raw_payload` may embed personal → strip at parse)

`id`, `source_key`, `snapshot_id` FK, `raw_payload` JSONB, `observed_at`,
`match_confidence`, `candidate_id` FK. One row per sighting. **Never overwritten.**
PR001 is one more source under this model, its bronze generations the file-shaped
equivalent.

### `practitioner` — PERSONAL DATA, restricted access

`practitioner_id` UUID PK · `name` · `mmc_no` · `provider_code` FK · `lawful_basis`
NOT NULL · `retention_until` NOT NULL · `purpose_note` · `source_key`.

Not returned by default API responses; Phase 3 adds elevated scope + access audit log.
PR001 supplies `DOCTOR_NAME` (13,496 real, 11,815 distinct) but **no MMC number**, so
`mmc_no` stays NULL from this source, and PR001 supplies neither `lawful_basis` nor
`retention_until` — the loader sets both explicitly at write time.

**Concrete trigger (2026-08-12):** PERKESO panel listings publish doctors' names
alongside clinic name, address, phone and clinic code. Any PERKESO adapter must route
names here with `lawful_basis` and `retention_until` set at write time. MyGeoCKAPS may
also expose practitioner names (open q. 19).

### `recency_signal` (business)

`candidate_id`, `signal_type` (`job_posting` | `socso_panel_add` |
`protecthealth_panel_add` | `first_google_review` | `grand_opening_post` |
`ckaps_new_registration` | `chain_announcement`), `signal_date`, `source_url`, `weight`.
Discovery-side; PR001 contributes nothing. `protecthealth_panel_add` is a strong signal —
joining a government payer panel demonstrates the clinic actively wants panel business
(ADR 0004).

### `panel_membership` (business) — **narrowed, restructure R2**

`provider_code` **or** `candidate_id`, `panel_owner` (`socso` | named competitor),
`status`, `observed_at`. **PMCare is no longer one panel among many**: PMCare panel state
is authoritative from `core.provider_outlet.pmcare_panel_status`, observed nowhere. This
table survives for SOCSO and competitor panels only.

### `snapshot`, `engagement`, `kpi_month` (business)

`snapshot` — `snapshot_id`, `source_key`, `taken_at`, `path`, `checksum` (sha256),
`row_count`. Immutable; the basis of all diffing, and exactly the bronze idempotency key.

`engagement` — `candidate_id`, `queue` (`a_new_opening` | `b_existing_not_on_panel`),
`priority_score`, `assigned_to`, `status`, `contact_attempts` JSONB[], `consent_state`,
`opt_out_at`. **Opt-out is permanent** — suppression must be provable (Phase 3).

`kpi_month` — `month`, `engaged_count`, `target_low` (40), `target_high` (60),
`queue_a_count`, `queue_b_count`. Baselined against
`core.v_kpi_appointments_monthly`.

## Restructures from the pre-PR001 design

| # | Change | Why |
|---|---|---|
| **R1** | The single golden `clinic` table **splits** into `core.provider_outlet` (incumbent) + `core.grid_candidate` (discovered), joined by `core.outlet_candidate_link`. `clinic` as previously specified is not built. | A single golden record cannot express incumbent versus candidate, which is the structural fact the project turns on. Both sides keep the same field shape and the same `coord_quality` enum. ADR 0005. |
| **R2** | `panel_membership` **narrows** to non-PMCare panels. | `PMCARE_PANEL_STATUS` is a first-class flag on the incumbent row — authoritative, not observed. |

Nothing was dropped. `clinic_source_record`, `practitioner`, `recency_signal`,
`snapshot`, `engagement` and `kpi_month` survive unchanged in shape; their `clinic_id`
FK becomes `provider_code` or `candidate_id` as the side requires.

## Migration status

No migrations have ever run. Alembic is initialised (`src/grid/db/migrations/`) and
`db/models.py` holds only the `DeclarativeBase`. The first revision implements the
schemas and tables above; it is a Phase 1 task and, per ADR 0006, is authored against
Postgres and exercised offline on SQLite with attached schemas. **No PostGIS geometry is
introduced by that revision** — the spatial layer is deliberately deferred and will be
untested until a Postgres instance exists (open question 2).
