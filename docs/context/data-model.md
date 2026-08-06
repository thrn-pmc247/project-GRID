---
title: Data Model
owner: thiran
last_verified: 2026-08-06
verify_by: 2026-11-04
covers_paths:
  - src/grid/db/**
status: current
---

# Data model

Designed here **before** migrations are written. Every column carries a
`pdpa_class`: `business` (default, low risk) or `personal` (full PDPA regime —
restricted table, lawful basis, retention, purpose; never in default API responses).
A sole proprietor's mobile that doubles as the clinic line is **personal**.

## `clinic` — golden record (all business-class)

| Column | Type | Notes |
|---|---|---|
| `clinic_id` | UUID PK | internal |
| `name_canonical` | text | normalised (see entity-resolution.md) |
| `name_variants` | text[] | every observed spelling |
| `address_canonical` | text | |
| `postcode` | char(5) | |
| `city`, `district` | text | |
| `state` | enum | canonical 16 states/FTs (`normalise/states.py`) |
| `geom` | PostGIS Point, SRID 4326 | |
| `phone_e164` | text | +60 E.164; personal if sole-proprietor mobile → moves table |
| `email_business` | text | business mailbox only |
| `website` | text | |
| `scope` | enum | `gp` \| `gp_with_interest` \| `specialist` \| `excluded` |
| `ckaps_reg_no` | text | Act 586 registration number |
| `google_place_id` | text | **the only Places content persisted** |
| `first_seen_at` | timestamptz | |
| `opened_estimate` | date | |
| `opened_confidence` | float | from recency-signal fusion |
| `status` | enum | active \| closed \| unverified |

## `clinic_source_record` — provenance (business; `raw_payload` may embed personal → strip at parse)

`id`, `source_key`, `snapshot_id` FK, `raw_payload` JSONB, `observed_at`,
`match_confidence`, `clinic_id` FK. One row per sighting. **Never overwritten.**

## `practitioner` — PERSONAL DATA, restricted access

| Column | Notes |
|---|---|
| `practitioner_id` UUID PK | |
| `name` | personal |
| `mmc_no` | personal — MMC registration number |
| `clinic_id` FK | |
| `lawful_basis` | recorded per row, NOT NULL |
| `retention_until` | date, NOT NULL |
| `purpose_note` | why we hold it |
| `source_key` | where it came from |

Not returned by default API responses; Phase 3 adds elevated scope + access audit log.

## `recency_signal` (business)

`clinic_id`, `signal_type` (`job_posting` | `socso_panel_add` | `first_google_review` |
`grand_opening_post` | `ckaps_new_registration` | `chain_announcement`),
`signal_date`, `source_url`, `weight`.

## `panel_membership` (business)

`clinic_id`, `panel_owner` (`pmcare` | `socso` | named competitor), `status`,
`observed_at`. Drives suppression and prioritisation.

## `snapshot` (business)

`snapshot_id`, `source_key`, `taken_at`, `path`, `checksum` (sha256), `row_count`.
Immutable; the basis of all diffing.

## `engagement` (business + consent state)

`clinic_id`, `queue` (`a_new_opening` | `b_existing_not_on_panel`), `priority_score`,
`assigned_to`, `status`, `contact_attempts` JSONB[], `consent_state`, `opt_out_at`.
**Opt-out is permanent** — suppression must be provable (Phase 3 acceptance).

## `kpi_month` (business)

`month`, `engaged_count`, `target_low` (40), `target_high` (60), `queue_a_count`,
`queue_b_count`.

## Migration status

No migrations exist yet. Alembic is initialised (`src/grid/db/migrations/`); the first
revision implements the tables above and is a Phase 1 task. `db/models.py` currently
holds only the `DeclarativeBase`.
