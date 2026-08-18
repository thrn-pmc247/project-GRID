# Reconciliation — PR001 provider master vs the existing GRID mockup

Date: 2026-08-17 · Author: Claude (agent) · Status: **awaiting human review of §5**
Source file profiled: `PR001.parquet` — 33,643 rows × 70 columns, ZSTD, single row group.

This note is Task 0 of the PR001 integration brief. **No schema or pipeline code was
written before it.** Its purpose is to state, before any build, exactly where the
designed-but-unbuilt mockup survives contact with the real incumbent extract and where
it does not.

---

## 0. Housekeeping done before profiling

| Finding | Action |
|---|---|
| `PR001.parquet` sat at the repo root, **untracked and not ignored** (`git status` showed `?? PR001.parquet`). `.gitignore` covered `/*.xlsx`, `/*.csv`, `/*.pdf` at root but had **no parquet rule**. One `git add -A` would have committed 13,496 real doctor names, 31,292 phone numbers and 4,017 e-invoice TINs. | `.gitignore` now carries `*.parquet` (any depth), `PR001*`, with `!tests/fixtures/pr001_profile.json` re-admitted. Verified with `git check-ignore`. |
| `PR001_provider_master.xlsx` (13.5 MB) also at root. Already ignored by `/*.xlsx`, **but** `scripts/check_context.py` check 13 globs the filesystem, not the index, so the gate fails on it today. | Flagged in §5 as item **D1** — it needs to move to `data/raw/`, which is a move of your data and therefore your call. |
| Parquet reader | `pyarrow` and `polars` are both **absent from `.venv`**; `pandas` 3.0.5 is installed *without* pyarrow, so it cannot read parquet at all. `polars>=1.0` is however **already declared** in `pyproject.toml` under the `perf` extra and already resolved in `uv.lock`. Installed via `uv sync --extra perf` (polars 1.43.2). **No new dependency was added** — see §6. |

`PR001.parquet` was left in place at the repo root; the loader takes an explicit path
argument, so it works from either location.

---

## 1. Entity-by-entity: what PR001 confirms, contradicts, or leaves unsupported

The mockup's authoritative schema is `docs/context/data-model.md`. Supporting artefacts:
`docs/handoff/openapi.json` (a **stub** — `{"status": "pending-phase-3"}`, no schemas),
`docs/handoff/grid-mockup.html` (a UI demo over fabricated data), `scripts/seed_synthetic.py`
(3 synthetic clinics), `src/grid/db/models.py` (**a bare `DeclarativeBase` — no tables**),
and `src/grid/db/migrations/versions/` (**empty — zero migrations exist**).

That last fact governs everything below: **nothing in the mockup is built yet, so no
change to it can destroy data.** The diff is a design diff.

### 1.1 `clinic` — golden record

| Mockup column | PR001 verdict | Evidence |
|---|---|---|
| `clinic_id` UUID PK | **unsupported** — PR001 has its own keys | `PROVIDER_CODE` 33,643/33,643 distinct; `ROW_GUID` 33,643/33,643 distinct |
| `name_canonical` | **confirmed** as necessary | `PROVIDER_DESCRIPTION` needs normalisation: 3,303 name groups cover 10,426 rows |
| `name_variants` text[] | **confirmed** | same |
| `address_canonical` | **contradicted as a single field** | address arrives as 3 free-text lines: `ADDRESS1` (33,381 real), `ADDRESS2` (27,198), `ADDRESS3` (17,929) |
| `postcode` char(5) | **contradicted** — `char(5)` would reject real data | 32,834 non-blank, only **32,649** match `^\d{5}$`. Invalids include `814000`, `8480`, `CV5 6J` (a UK postcode), and `40000�` (encoding corruption) |
| `city`, `district` | **partially unsupported** | `CITY` is free text, 1,019 distinct, no controlled vocabulary. **No `district` column exists in PR001.** |
| `state` enum, "canonical 16 states/FTs" | **contradicted** — see §2.2 | 18 distinct `STATE_CODE` values: 15 plausible + `PJ` (118) + `ZZ` (29) + `00` (1) |
| `geom` PostGIS Point, SRID 4326 | **contradicted — the headline casualty.** See §2.1 | 17,525 rows NULL; of 16,118 populated only **9,878** are a plausible Malaysian pair |
| `phone_e164` | **confirmed, but personal** | `GENERAL_PHONE_NO` 31,292 real; `APPS_PHONE_NO` 2,819 |
| `email_business` "business mailbox only" | **contradicted** | the only email in PR001 is `einv_email` (3,997) — an **e-invoicing** contact, frequently a sole proprietor's own address. Not a clean business mailbox. |
| `website` | **contradicted — field is unusable** | `WEBSITE` has 83 real values / 73 distinct table-wide, and populated values include staff names (`MS. YAP`, `JAYANTHI`). Not a web-presence signal. |
| `scope` enum `gp\|gp_with_interest\|specialist\|excluded` | **superseded by a real code** | `PROVIDER_TYPE_CODE`, 21 distinct: `GP` 13,552, `OP` 7,000, `DT` 5,140, `SP` 2,573, `PH` 1,115, `LB` 776 … 14 codes unresolved |
| `ckaps_reg_no` "Act 586 registration number" | **unsupported — do not assume `HBRN` is it** | `HBRN` has 4,796 real values (14% fill). Whether it is the MOH/PHFSA facility registration number is **unknown** → open question |
| `mygeockaps_id` | **not applicable** — discovery-side field | PR001 is the incumbent side |
| `status_operasi` | **not applicable** | same |
| `google_place_id` | **unsupported** | absent, correctly |
| `first_seen_at` | **not applicable** to an incumbent | PR001 has `CREATE_DATE` (0 null) — a different concept: when PNM keyed the record |
| `registered_at` | **unsupported** | no registration date. `APPOINMENT_DATE` (0 null, 1995-05-02 → 2026-08-05) is the **panel-appointment** date, not registration |
| `opened_estimate`, `opened_confidence` | **not applicable** — discovery-side | — |
| `status` enum `active\|closed\|unverified` | **contradicted** | `STATUS_CODE` is a 4-value code: `A` 29,591, `T` 4,032, `S` 17, `V` 3. `S` (suspended) has no home in the mockup enum, and `V` is unknown |

**Structural verdict on `clinic`:** the mockup models one golden record per real-world
clinic, conflating *the network PMCare already has* with *clinics GRID discovers*. PR001
forces these apart. See §3.1.

### 1.2 Remaining mockup entities

| Entity | Verdict |
|---|---|
| `clinic_source_record` | **confirmed and reusable.** PR001 becomes one more source with immutable per-sighting provenance. Its bronze generation model (§ Task 2) is the same idea applied to a file. |
| `practitioner` | **confirmed as the right shape, partially unsupported.** `DOCTOR_NAME` (13,496 real, 11,815 distinct) routes here. But PR001 carries **no MMC number**, so `mmc_no` stays NULL from this source. `lawful_basis` / `retention_until` are `NOT NULL` in the mockup — PR001 supplies neither, so the loader must set them explicitly at write time. |
| `recency_signal` | **unaffected.** Discovery-side. PR001 contributes nothing. |
| `panel_membership` | **scope narrowed.** The mockup treats `pmcare` as one observed panel among many. PR001 carries `PMCARE_PANEL_STATUS` as a **first-class boolean on the incumbent row** (GP + status A + panel = 5,956). PMCare's own panel state is now authoritative from PR001, not observed; the table survives for SOCSO/competitor panels. |
| `snapshot` | **confirmed, extended.** `checksum` (sha256) + `row_count` is exactly the bronze idempotency key. |
| `engagement` | **unaffected.** |
| `kpi_month` | **confirmed, and PR001 supplies the baseline** — see Task 7. |

---

## 2. Mockup assumptions PR001 breaks

The brief named coordinates, SSM linkage and name uniqueness as the three likely
casualties. All three are casualties. A fourth (state enum) and a fifth (postcode type)
also fail.

### 2.1 Coordinates — the most consequential break

`docs/context/data-model.md` states:

> "`geom` is populated natively from MyGeoCKAPS (`esriGeometryPoint`, SRID 4326) rather
> than geocoded, **so PostGIS is load-bearing from the first migration**."

and `docs/context/entity-resolution.md` blocks on `postcode` → `phone_e164` →
name trigrams, with no coordinate stage.

That claim is about MyGeoCKAPS and remains plausible **for the discovery side**. It is
false for the incumbent side, and the incumbent side is the reconciliation target:

| coord_quality | rows | share |
|---|---|---|
| MISSING (either component NULL) | 17,525 | 52.1% |
| NULL_ISLAND — exactly (0, 0) | 6,210 | 18.5% |
| OUT_OF_BOUNDS | 30 | 0.1% |
| VALID (lat 0.85–7.40, lon 99.60–119.30) | 9,878 | 29.4% |
| **total** | **33,643** | **100%** |

**Only 29.4% of the incumbent master can support a coordinate comparison at all.** A
coordinate-primary matcher is therefore rejected outright (ADR 0005). Note also that the
dominant failure is not noise but a specific sentinel — 6,210 rows at exactly (0,0),
i.e. 99.5% of all out-of-range values are one imputation bug, not scattered typos.

Worth recording because it constrains the repair logic: the 30 genuinely out-of-bounds
rows include `PHAR918` (lat 932799.0), `N1314` (lon 1.9567e14), `DEN3105` (27.20, 117.69
— China), and `OPT6018` (lat == lon == 3.0638). See §5 item **A1** for a decision I need
from you on the repair rule.

### 2.2 State enum — "the canonical 16 states/FTs" is not what the data holds

`data-model.md` says `state` is an "enum | canonical 16 states/FTs (`normalise/states.py`)".
PR001 holds **18** `STATE_CODE` values, and only **15** are plausibly real:

`SL` 10,220 · `KL` 5,813 · `JB` 3,431 · `PR` 2,247 · `PG` 2,080 · `SR` 1,531 · `SB` 1,420 ·
`KD` 1,419 · `NS` 1,351 · `PH` 1,079 · `ML` 1,069 · `KN` 901 · `TR` 751 · `PE` 136 · `LA` 47

That is 13 states + Kuala Lumpur + Labuan. Putrajaya — the third federal territory — is
**absent unless `PJ` (118 rows) is it**, which the data does not prove. Plus `ZZ` (29) and
`00` (1), which are not states at all. A closed 16-value enum would reject 148 real rows.
`state_code` is therefore modelled as a **FK to a reference table that can hold "unknown"**,
not an enum.

### 2.3 SSM linkage — absent, as suspected

Nothing in the mockup claims SSM linkage (guardrail 2 forbids scraping it), so strictly
this breaks no stated assumption. But it kills a plausible shortcut, so it is recorded:
`GST_COMPANY_REG_NO` has **125 real values out of 33,643 (0.37%)**, and they are not even
consistently registration numbers — the 125 include `JKLE SDN BHD` (a company *name*),
`R75292/24`, `42140101`, alongside genuine 12-digit SSM numbers (`202501030274`) and old-format
ones (`591650-X`). **There is effectively no SSM linkage in this data and no route to one.**
Entity resolution cannot lean on company registration at any point.

### 2.4 Name uniqueness — broken, and chains are the reason

`entity-resolution.md` targets "one golden `clinic` record per real-world clinic".
`PROVIDER_DESCRIPTION` is not unique: **3,303 name groups cover 10,426 rows** (31% of the
master). Largest: `KLINIK MEDIVIRON` ×131, `FOCUS POINT VISION CARE GROUP SDN BHD` ×104,
`FOCUS POINT VISION CARE GROUP` ×87, `U.N.I KLINIK` ×62, `KLINIK PERGIGIAN TIEW` ×56.

Two distinct causes, and conflating them would be a serious modelling error:

1. **Genuine multi-outlet chains.** 131 Mediviron rows are 131 real, separately-appointed
   premises. They must stay 131 rows.
2. **The same name recorded twice** for one premises (re-keying, code changes).

Note `FOCUS POINT VISION CARE GROUP SDN BHD` (104) and `FOCUS POINT VISION CARE GROUP` (87)
are the *same chain* under two spellings — so normalisation must strip corporate suffixes
before grouping, exactly as the brief specifies. The trailing-parenthesis branch pattern
the brief describes is real and large: **4,155 names end in `(...)`**, e.g.
`KLINIK SUREN (TMN KERAMAT)`, `SABAK DISPENSARY (SG BESAR)`.

**Consequence:** `name_canonical` alone can never be an identity key. Blocking must be
`name_normalised + postcode`, and chain membership must be inferred with a confidence
value, never asserted.

### 2.5 `postcode char(5)` would reject real rows

Covered in §1.1. Modelled as `text` + a validity flag + `postcode_state_mismatch`, never
coerced.

### 2.6 A quieter break: `status` is not a lifecycle the mockup anticipated

`TERMINATION_DATE` is populated for **exactly** the 4,032 `T` rows and `SUSPENSION_DATE`
for **exactly** the 17 `S` rows (0 code-without-date, 0 date-without-code in both cases).
That perfect cross-field consistency is the evidence for seeding `ref_status`.

But `TERMINATION_DATE` reaches **2028-08-05**. As of today (2026-08-17) exactly **one** row
is future-dated. So `status = active` cannot be `termination_date IS NULL` — it needs a
point-in-time function. The population is one row today, but it is a correctness trap that
grows, and re-running a historical month would silently get the wrong answer.

---

## 3. PR001 concepts the mockup has no home for

| PR001 concept | Evidence | Where it must go |
|---|---|---|
| **Incumbent vs candidate as distinct kinds** | 33,643 incumbent rows exist; GRID's job is to find what is *not* here | **`core.provider_outlet`** (incumbent, from staging only) vs **`core.grid_candidate`** (discovered) vs **`core.outlet_candidate_link`** (the resolution edge). The mockup's single `clinic` has no way to express this. |
| **Provider type as a 21-value vocabulary** | `PROVIDER_TYPE_CODE`; 14 codes unresolved | `ref_provider_type` with `source ∈ {confirmed_by_pnm, inferred, unknown}` |
| **PNM's own duplicate-resolution history in free text** | `REMARKS` 27,052 real / 11,055 distinct; `DUPLICATE` 356, `CLOSED` 537 | `core.remarks_signal` + `core.provider_code_supersession`. **No mockup equivalent whatsoever.** See §4 for a significant downgrade to the brief's expectation here. |
| **Chains as first-class** | 3,303 name groups / 10,426 rows | `core.chain`, `core.outlet_chain_member` |
| **Code supersession as a directed graph** | `CHANGE TO` 167 remarks | `core.provider_code_supersession` |
| **Sentinel values, not NULL** | `ACC_VENDOR_FLAG_DATE = 1900-01-01` in **12,877** rows; `00:00:00` in the 836 populated hour rows | staging remaps to NULL and **logs the count** |
| **Mixed-case user identities** | `STATUS_BY` 76 raw → 70 folded; `MODIFY_BY` 87 → 81; `CREATE_BY` 47 → 41; `GL_ELIGIBILITY_APPROVE_BY` 24 → 15 | `ref_user`, canonical lowercase key, raw variants retained |
| **Credential payload + internal infrastructure path** | `QR_ENCRYPTED_TEXT`, `QR_FILE_PATH` (contains `\\10.51.51.99\LineDoc\...`) | **quarantine — bronze only**, never in an analytical or shareable layer |
| **Blank string as the real "empty"** | `WEBSITE`: 13,708 NULL **+ 19,852 blank** → 83 real. `HBRN`: 13,393 NULL + 15,454 blank → 4,796 real | the profiler must count blanks separately from nulls, or every fill rate in this project will be wrong |
| **Boolean columns named like counts** | `NO_DOCTOR_MALE`, `NO_DOCTOR_FEMALE` are `BOOLEAN` | modelled as boolean; intent is an open question |
| **A load-log discipline** | — | `ops.load_log`, `ops.transform_log`; threshold breach raises |

---

## 4. Correction to the brief's own expectations (Task 6)

The brief calls the supersession graph "the single most valuable artefact in the free
text". Profiling does not support that framing, and the build should not be sized for it:

| Brief's named pattern | Actual occurrences in 27,052 non-blank remarks |
|---|---|
| `WRONG CODE - CHANGE TO 101252` | `WRONG CODE` **8** |
| `ALREADY IN CMS` | **1** |
| `WRONGLY KEYIN` | **1** |
| `RA …(TERM …)` reappointment | `^RA ` **11** |
| `CHANGE TO` (any form) | **167** |
| *unnamed by the brief:* `DUPLICATE` | **356** |
| *unnamed by the brief:* `CLOSED` | **537** |

Two things follow:

1. **The brief's named patterns are near-singletons.** `ALREADY IN CMS` and `WRONGLY KEYIN`
   occur once each. They are worth extracting, but they are not a corpus.
2. **A naive `CHANGE TO (\S+)` regex is 0.6% precise.** Of 167 matches, exactly **1**
   yields a token that resolves to a real `PROVIDER_CODE`. The real codes are parenthesised
   or trail a keyword: `TERMINATE CHANGE TO NEW CODE (102382)`, `CHANGE TO CODE 201026`,
   `TERMINATE CHANGE TO NEW CODE(206328)`. And `PROVIDER_CODE` is **not numeric** — it
   ranges over `GOH`, `0101252`, `DEN4022`, `OPT6018`, `PH036`, `N1386`, lengths 5–12.

   So the miner is built the other way round, honouring "precision over recall": tokenise
   the remark, keep only tokens that **exist in the 33,643-code universe**, and require a
   supersession keyword in the fragment. An edge is emitted only when its target is a real
   provider code. This is deterministic and auditable; recall will be modest and that is
   the correct trade.

`DUPLICATE` (356) and `CLOSED` (537) are added as evidenced signal types, per the brief's
instruction to "let the profiler tell you what else is frequent".

---

## 5. Proposed diff — and what I need from you

### Non-destructive, proceeding (nothing exists to destroy: 0 migrations, 0 tables)

| # | Change | Effect on mockup |
|---|---|---|
| N1 | Add schemas `bronze`, `staging`, `core`, `ops`, `pii` | additive |
| N2 | Add `bronze.pr001_provider_master` (70 cols verbatim + 5 `_` audit cols) | additive |
| N3 | Add `staging.ref_*` (7 tables) + `ref_user` + `ref_city` | additive |
| N4 | Add `staging.provider_outlet` | additive |
| N5 | Add `core.provider_outlet`, `core.chain`, `core.outlet_chain_member`, `core.grid_candidate`, `core.outlet_candidate_link` | additive |
| N6 | Add `core.remarks_signal`, `core.provider_code_supersession` | additive |
| N7 | Add `ops.load_log`, `ops.transform_log` | additive |
| N8 | Add `pii.provider_contact` + shareable views | additive |
| N9 | `tools/profile_parquet.py` + fixture + drift test | additive |

### Restructures — 2 entities, both below the brief's stop-threshold of 3

| # | Change | Why |
|---|---|---|
| **R1** | **`clinic` splits into `core.provider_outlet` (incumbent) + `core.grid_candidate` (discovered), joined by `core.outlet_candidate_link`.** `clinic` as specified is not built. | §1.1, §3. A single golden record cannot express "incumbent master vs discovery candidate", which the brief identifies as *the* structural fact. Both sides keep the same field shape and the same `coord_quality` enum so they stay comparable field-for-field. |
| **R2** | **`panel_membership` narrows** to non-PMCare panels; PMCare panel state comes from `PR001.PMCARE_PANEL_STATUS` on the incumbent row. | §1.2 |

Nothing is dropped. `clinic_source_record`, `practitioner`, `recency_signal`, `snapshot`,
`engagement`, `kpi_month` are unchanged. **2 entities restructured < 3 → per the brief I
continue past this note.**

### Flagged for your approval — NOT executed

| # | Item | Why it is yours |
|---|---|---|
| **D1** | **Move `PR001_provider_master.xlsx` and `PR001.parquet` out of the repo root into `data/raw/pr001/`.** | Moving your data files is not mine to do unilaterally. Until this happens `check_context.py` check 13 **fails** on the stray root `*.xlsx` (it globs the filesystem, not the git index — being gitignored does not satisfy it). I have not moved, renamed or deleted either file. |
| **A1** | **Coordinate decimal-shift repair rule — literal reading recovers ~0 rows.** The brief says "divide by successive powers of ten up to 10^12, accept only if **a single power lands both lat and lon in range**". Taken literally, both components are divided by the *same* power; since most broken rows have one *valid* component and one inflated one (e.g. `DEN2559` lat 3.112491 ✓, lon 101591143.0 ✗), any power that fixes the bad one destroys the good one. Literal rule → **0 repairs**. I implemented the conservative variant: search a power **per component**, require that power to be **unique** for that component, and require the resulting **pair** to be in bounds; ambiguous → `OUT_OF_BOUNDS`. This is still non-coercive. Actual recovery is reported at the end of the build. Say the word if you want the literal rule instead. |
| **A2** | `PJ` (118 rows) seeded as `inferred` = Putrajaya **with a note**, per the brief. It is a guess about real data — confirm or correct it. Open question raised. |

### Deviations from the brief's stated paths

The brief refers to `docs/adr/`, `docs/data-model.md`, `docs/architecture.md`,
`docs/open-questions.md` etc. **None of those paths exist.** This repo uses
`docs/decisions/` for ADRs and `docs/context/*.md` for context files, and
`scripts/check_context.py` enforces that layout (front matter, pointer table, INDEX).
I have used the **real** paths: ADR 0005 → `docs/decisions/0005-…md`, data model →
`docs/context/data-model.md`, open questions → `docs/context/open-questions.md`.

---

## 6. Dependencies

**No new runtime dependency is added.** `polars>=1.0` was already declared in
`pyproject.toml` (`[project.optional-dependencies] perf`) and already pinned in `uv.lock`;
it was simply not installed in `.venv`. It is now installed via `uv sync --extra perf`.

Two consequences worth stating:

- **`pandas` cannot be used for this work.** pandas 3.0.5 is installed without `pyarrow`
  and therefore cannot read parquet. Adding `pyarrow` would be a genuine new dependency
  *and* a second parquet stack, which the brief forbids. Polars it is.
- **Parquet reading moves from optional to required** for the PR001 path. The `perf` extra
  is now load-bearing, which is a mislabel; `pyproject.toml` should eventually promote
  polars to a main dependency or rename the extra. Flagged, not silently changed.

**Database engine.** Open question 2 records that Docker Desktop is not installed, so no
Postgres/PostGIS instance exists to migrate against. The layer model uses real SQL schemas
(`bronze.`, `staging.`, `core.`), which SQLite normally cannot express — but SQLite
`ATTACH DATABASE` provides genuine schema-qualified names. The build therefore targets
Postgres via SQLAlchemy 2.0 (already a dependency) and runs offline/in tests on SQLite
with attached schemas. Recorded as ADR 0006.

---

## 7. Verified-facts audit

Every figure the brief supplied was re-checked against the file. All material claims hold.
Four are restated more precisely, because the difference changes code:

| Brief's claim | Measured | Note |
|---|---|---|
| 33,643 × 70; `PROVIDER_CODE`/`ROW_GUID` unique | ✅ exact | |
| `MIX_ROW_ID` not unique, 15 collide | ✅ 33,628 distinct = 15 fewer | never keyed |
| GP 13,552 → A 10,506 → panel 5,956 | ✅ exact | |
| `A` 29,591 · `T` 4,032 · `S` 17 · `V` 3 | ✅ exact | |
| 17,525 coords NULL | ✅ exact | |
| "roughly 9,884 rows (29%) plausible" | **9,878** (29.4%) | inclusive bounds as specified |
| "6,219 latitudes … outside Malaysia" | **6,210 are exactly (0,0)**; only **30** are otherwise out of bounds | reframes the repair work entirely — §2.1 |
| 32,834 postcodes populated / 32,649 valid | ✅ exact | |
| `CITY` 1,018 distinct | 1,019 non-null distinct | off-by-one; immaterial |
| `WEBSITE` 72 distinct | 73 distinct / 83 real values | immaterial |
| 125 rows with `GST_COMPANY_REG_NO` | ✅ **125 non-blank** — but **18,164 non-NULL** | the gap is 18,039 blank strings. This is why blank-counting is mandatory. |
| `isPERKESO` true for 114 | ✅ exact | |
| hour columns populated for 836 (2.5%) | ✅ exact | |
| `ACC_VENDOR_FLAG_DATE` 1900-01-01 sentinel | ✅ — in **12,877** rows (38%) | count not previously stated |
| future-dated terminations exist, max 2028-08-05 | ✅ max exact; **exactly 1** row is after today | §2.6 |
| `DOCTOR_NAME` 11,814 distinct | 11,815 non-null distinct / 13,496 real | immaterial |
| `REMARKS` 11,054 distinct | 11,055 non-null distinct / 27,052 real | immaterial |
| 9 INT64→TIMESTAMP(µs), 4 TIME(ns) | ✅ confirmed via polars logical types | |

---

## 8. Schema contract fixed by this note

Recorded here so parallel work cannot diverge. Full detail in `docs/context/data-model.md`.

```
bronze.pr001_provider_master     70 verbatim cols + _ingest_id, _ingested_at,
                                 _source_filename, _source_sha256, _row_ordinal
staging.ref_provider_type | ref_state | ref_status | ref_category
       | ref_payment_method | ref_ownership | ref_lk180 | ref_user | ref_city
staging.provider_outlet          33,643 rows; UNIQUE(provider_code), UNIQUE(row_guid);
                                 mix_row_id nullable, non-indexed, no constraint
core.provider_outlet             incumbent network — from staging only
core.chain | core.outlet_chain_member
core.grid_candidate              discovered clinics, same shape + same coord_quality enum
core.outlet_candidate_link       resolution edge; human decisions immutable and overriding
core.remarks_signal | core.provider_code_supersession
core.v_kpi_appointments_monthly  GP series separable; excludes superseded codes
ops.load_log | ops.transform_log
pii.provider_contact             personal data; excluded from default analytical views
```

Blocking key for resolution: `name_normalised + postcode`. Coordinates are
**confirmatory only**, gated on `coord_quality = 'VALID'` on **both** sides.

---

## 9. Build results (2026-08-17)

Measured on the real extract, `PR001.parquet`, SHA-256 `b0aa316e…`.

### Rows at each layer

| Layer | Rows | Note |
|---|---|---|
| `bronze.pr001_provider_master` | **33,643** × 75 cols | 70 verbatim + 5 audit; reload is a no-op |
| `staging.provider_outlet` | **33,643** | unique on `provider_code` and `row_guid`, both holding |
| `core.provider_outlet` | **33,643** | |
| `pii.provider_contact` | **33,643** | segregated schema |

### Coordinate gate — reconciles to 33,643

| coord_quality | rows |
|---|---|
| MISSING | 17,525 |
| NULL_ISLAND | 6,210 |
| VALID | 9,878 |
| REPAIRED_DECIMAL | 12 |
| REPAIRED_SPLIT | 0 |
| OUT_OF_BOUNDS | 18 |
| **total** | **33,643** |

**What the repairs recovered: 12 rows** (0.036%), all decimal-shift; the split rule
fired zero times, as anticipated. Two further candidates were deliberately *abandoned*
by an axis-swap guard added during review: `OPT6002` (103.14, 101.66) and `OPT6022`
(103.76, 103.80) both carry a latitude that is itself a valid longitude, making
swap-versus-shift ambiguous — and the brief requires ambiguity to abandon the repair.

**Known limitation, recorded rather than papered over:** the valid-bounds test is a
rectangle that also contains Sumatra, most of Kalimantan, Singapore, Brunei, southern
Thailand and open sea. `DEN3105` (33.9651, 117.6911) repairs by a genuinely unique power
to (3.39651, 117.6911), which is in East Kalimantan, not Sabah. **Neither `VALID` nor a
repaired verdict is proof a point is in Malaysia.** A polygon test would settle it; the
project has no polygon. Raised as an open question.

### Other transform counts

| Transform | Count |
|---|---|
| `ACC_VENDOR_FLAG_DATE` 1900-01-01 sentinel → NULL | 12,877 |
| rows with usable operating hours (`operating_hours_present`) | 544 |
| non-blank postcodes failing `^\d{5}$` | 184 |
| postcode/state disagreements flagged (never overwritten) | 405 |
| staff identities after case-folding | 97, from 14 case collisions |
| `ref_city` entries seeded (city + postcode prefix) | 1,241 |
| `ref_postcode_prefix_state` prefixes derived empirically | 84 |
| `mix_row_id` colliding groups retained, unconstrained | 15 |

### Chains and REMARKS

- **4,122 chains inferred**, **14,327 memberships**, each with a confidence — never asserted.
- **2,633 REMARKS signals**: `file_or_onboarding_date` 1,530 · `closed` 542 ·
  `duplicate_flag` 356 · `code_supersession` 169 · `reappointment` 18 · `new_provider` 12 ·
  `keying_error` 9 · `relocation` 2 · `known_duplicate` 1.
- **96 supersession edges, 0 cycles.** Against a naive `CHANGE TO (\S+)` regex, which
  resolves exactly 1 of 167, the code-universe-validated approach recovers 96 — a 96×
  improvement, every edge with both endpoints a real `PROVIDER_CODE`.

### KPI baseline — reconciles to the brief

| Figure | Value |
|---|---|
| 2026 appointments, all types, before exclusion | **1,114** — matches the brief exactly |
| of which superseded, therefore excluded | 6 |
| 2026 appointments in `core.v_kpi_appointments_monthly` | **1,108** |
| 2026 **GP-only** appointments | **423** |

The 6-row deduction is the re-keying correction working as specified: a clinic re-keyed
under a new provider code is counted once, not twice.

### PDPA

All three shareable views expose **zero** restricted columns; quarantine holds
(`QR_ENCRYPTED_TEXT`, `QR_FILE_PATH` never leave bronze); 13,496 doctor names carry an
HMAC-SHA256 digest keyed on a salt read from `GRID_PII_HASH_SALT`, which raises rather
than defaulting.

### Two defects found during review, both fixed

1. **`backfill_row_counts` was silently a no-op** for 5 of the 7 reference tables —
   `row_count` stayed NULL. Cause: helper functions opened their own `engine.connect()`
   *inside* an open `Session`, and on an in-memory SQLite engine `StaticPool` returns the
   *same* DBAPI connection, so closing it mid-loop rolled the session's pending updates
   back. Fixed by reading all counts before the session opens. Affects only the
   informational `row_count` column, so no figure above moves.
2. **The pipeline was not re-runnable over a single extract.** Bronze was idempotent, but
   `transform_staging` derives `load_id` from `ingest_id`, so a second run collided on the
   `ops.load_log` primary key and raised `IntegrityError` — which would have broken the
   monthly refresh runbook and any retry after a partial failure. Fixed as
   **replace-on-rebuild**: staging deletes and rewrites its own accounting rows, matching
   what the layer already does with its data. The append-only record of what actually
   arrived stays in `bronze.pr001_generation`, which is never rewritten. Asserted by
   `test_whole_pipeline_is_rerunnable`.

### Quality gates

`mypy src/grid` — clean, 34 files, no `type: ignore` anywhere. `ruff check` and
`ruff format --check` — clean across 96 files. **512 tests pass**; the only failing test
is `check_context.py`'s, blocked solely by item **D1** (the stray root `*.xlsx`).
