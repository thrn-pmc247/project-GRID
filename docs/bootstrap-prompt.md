# Project GRID — bootstrap brief (verbatim, received 2026-08-06)

> This is the founding brief for the repository, preserved as received. Where this
> brief conflicts with defaults, this brief wins. Operational truth evolves in
> `CLAUDE.md` + `docs/context/` — if this file and the context system disagree, the
> context system is current.
>
> **Known superseded section (2026-08-12, ADR 0004):** the source plan below —
> `sources/ckaps.py` parsing Act 586 register PDFs as the PRIMARY Phase 1 spine, the
> `pdf-reading` skill prerequisite, and the monthly PDF refresh cadence — has been
> replaced by the MyGeoCKAPS ArcGIS REST service (layer 5). The published PDFs proved
> to be 2022/2023 vintage. Do not follow the source sections of this brief as current
> instruction; see `docs/context/data-sources.md`.

---

You are the lead engineer on **Project GRID** (*GP Registry & Intelligence Database*), a greenfield Python project. Read this entire brief before writing any code. Where this brief conflicts with your defaults, this brief wins. Where something is genuinely undetermined, add it to `docs/context/open-questions.md` and ask me — do not guess and do not invent facts, statutes, or figures.

## 1. Mission

PMCare is a Malaysian third-party administrator / managed care organisation (TPA/MCO). Its Provider Network Management (PNM) team must **engage 40–60 new GP clinics per month** to hit a KPI. Today that discovery is manual.

GRID is the automated discovery pipeline that finds them. It:

1. Discovers newly opened and newly registered **private GP clinics** across all of Malaysia (13 states + WP Kuala Lumpur, WP Putrajaya, WP Labuan, including Sabah and Sarawak).
2. Extracts and normalises clinic **business contact details and location**.
3. Deduplicates across sources, resolves entities, and **suppresses clinics already on the PMCare panel**.
4. Serves a ranked, filterable engagement queue to the PNM team via an API.

**Scope is GP / primary care only** (`Klinik Umum` / klinik perubatan). Explicitly out of scope: dental (klinik pergigian), specialist centres, physiotherapy, diagnostic labs, hospitals, aesthetics-only clinics. Most sources mix these categories — GP filtering is a first-class requirement, not an afterthought.

### Volume reality that shapes the architecture

MOH's registered private medical clinic count went 10,495 (2023) → 11,067 (2024): **+572 net, ~48 net-new per month**. Gross openings are higher, but realistic automated detection within 60 days is roughly **30–50/month with month-to-month variance that will sometimes dip below 40**.

**Therefore GRID has two queues, and both are first-class:**

- **Queue A — New openings.** Time-sensitive, highest conversion (a brand-new clinic actively wants panels). Priority.
- **Queue B — Existing registered GP clinics not yet on the PMCare panel.** Several thousand deep. This is the volume buffer that guarantees the KPI is met in a slow month.

Do not build a new-openings-only pipeline. It will miss the KPI.

## 2. Non-negotiable guardrails

These are hard constraints. Encode them in `CLAUDE.md` inline (not in a linked file — they must always be in context) and enforce them in code where possible.

### Source access

| Rule | Reason |
|---|---|
| **Never crawl `hq.moh.gov.my`.** It returns `ROBOTS_DISALLOWED`. Ingest CKAPS register PDFs via **scheduled manual download** into `data/raw/ckaps/<YYYY-MM-DD>/`, then parse locally. | MOH does not sanction automated crawling. |
| **Never scrape SSM** (MyData / e-Info / EzBiz). ToS prohibit automated scraping and bulk harvesting. | Use paid per-document access or a licensed reseller if SSM data is ever needed. |
| **Google Places: store `place_id` indefinitely; do not persist other Places content.** Refresh on read. | Google Maps Platform ToS restricts caching of Places content. |
| Respect `robots.txt` and per-site ToS for every adapter. Rate-limit, set a descriptive User-Agent, back off on 429/403. | Job boards and directories have anti-scraping terms. |
| Every adapter declares its legal basis in code metadata (see §8 adapter contract). No adapter ships without it. | Auditability. |

### Data protection (PDPA 2010 as amended by the PDP (Amendment) Act 2024)

- **Segregate business data from personal data at the schema level, from day one.**
  - **Business (low risk, the default):** clinic name, business address, postcode, state, main clinic phone line, Act 586 registration number, website, operating hours.
  - **Personal (full PDPA regime):** individual practitioner names, MMC registration numbers, personal mobile numbers, personal emails.
- Personal data lives in a separate table with restricted access, a recorded lawful basis, a retention period, and a purpose note. It is **not** returned by default API responses.
- Where a sole-proprietor clinic's "business" mobile is also the owner's personal mobile, **treat it as personal data**.
- Mandatory DPO appointment and breach notification have been in force since 1 June 2025. Build a breach-notification runbook in `docs/runbooks/`.
- **Never commit real clinic data, PII, exports, or credentials to git.** `.gitignore` must exclude `data/`, `.env`, `*.db`, `exports/`, `*.xlsx`, `*.csv` at repo root. Ship `data/` fixtures as synthetic only.

### Outreach

- The Communications and Multimedia (Amendment) Act 2025 commenced 11 Feb 2025, but **s.233A (unsolicited commercial electronic messages) is not yet in force** — it awaits subsidiary regulations. Treat it as imminent.
- **Do not build mass automated WhatsApp/email blasting.** Design consent-first and phone-first: outreach targets the clinic's **published business line**, every contact attempt is logged, opt-out is recorded and permanently honoured.
- The outreach API layer captures consent state and suppression flags. Any actual send capability is gated behind a config flag defaulting to `false` and requires PMCare compliance sign-off before enabling. Put this in `docs/context/compliance-outreach.md`.

### Positioning and content

- PMCare is a **neutral TPA — not the insurer, not the treating clinician.** Never generate copy that positions PMCare as making clinical decisions or bearing insurance risk.
- **British/Malaysian English spelling throughout** (organisation, normalise, licence as noun, centre). Currency as **RM**.
- Any outward-facing artefact (clinic correspondence, provider advisories, regulatory submissions, insurer decks) is **draft-only and marked as requiring human review** before sending.
- Never invent statutory citations, registration numbers, or statistics. Cite the specific provision. Flag uncertainty as uncertainty.
- Commercial terms, pricing, and contract questions go to the business owner — do not answer them in code comments or docs as if settled. This includes Google Maps Platform spend: put estimates in `docs/context/costs.md` marked **requires business owner sign-off**.

## 3. What Claude Code builds vs what Claude Design builds

**Claude Code (this repo):** source adapters, PDF parsing, entity resolution, normalisation, the Postgres/PostGIS warehouse, snapshot diffing, scoring, the FastAPI service, CLI tooling, tests, XLSX exports, docs.

**Claude Design (later, separate):** the PNM-facing dashboard UI.

Phase 3 therefore produces two handoff artefacts:
- `docs/handoff/openapi.json` — generated from FastAPI.
- `docs/handoff/design-brief.md` — user stories, the exact fields the dashboard shows, filter/sort dimensions, the KPI widget spec, empty/loading/error states, and the PMCare brand tokens.

Do not build dashboard UI in this repo beyond a bare `/docs` Swagger page and an optional throwaway `scripts/dev_preview.py`.

## 4. Environment

Windows 11, repo at `C:\Users\thiranbarath\Documents\GitHub\project-grid`.

- **Python 3.12** managed with **`uv`** (`uv venv`, `uv sync`, `uv run`). Fall back to `py -3.12 -m venv .venv` if `uv` is unavailable.
- **Postgres 16 + PostGIS via Docker Desktop** (`docker compose up -d db`). Provide `compose.yaml`. Migrations via **Alembic**.
- **Windows specifics you must handle:** commit a `.gitattributes` with `* text=auto eol=lf`; write git hooks in **Python, not bash**; never hardcode `/` path separators — use `pathlib`; keep `poppler` (for `pdfinfo`/`pdftotext`/`pdftoppm`) either as an optional dependency with a documented install path or use pure-Python `pdfplumber`/`pypdf` as the primary route so the pipeline runs without system binaries.
- Core deps: `httpx`, `playwright`, `pdfplumber`, `pypdf`, `pandas`, `polars` (optional), `rapidfuzz`, `phonenumbers`, `sqlalchemy`, `alembic`, `psycopg[binary]`, `geoalchemy2`, `pydantic`, `pydantic-settings`, `fastapi`, `uvicorn`, `prefect` (or `apscheduler` for a lighter start), `structlog`, `typer`, `openpyxl`, `pytest`, `pytest-cov`, `ruff`, `mypy`, `pre-commit`.
- Start with **APScheduler + Typer CLI**, not Prefect, unless orchestration complexity justifies it. Note the decision as an ADR.

## 5. Repository structure

Create exactly this. Every directory gets a `README.md` or `.gitkeep`.

```
project-grid/
├── CLAUDE.md                        # ≤150 lines. Router + hard guardrails only. See §6.
├── README.md                        # Human onboarding: what/why/quickstart
├── pyproject.toml
├── uv.lock
├── compose.yaml                     # Postgres + PostGIS
├── .env.example                     # every var documented, no real values
├── .gitignore
├── .gitattributes                   # * text=auto eol=lf
├── .pre-commit-config.yaml
│
├── .claude/
│   ├── settings.json                # hooks + permissions (committed)
│   ├── settings.local.json          # personal overrides (gitignored)
│   ├── commands/                    # custom slash commands
│   │   ├── context-audit.md
│   │   ├── context-update.md
│   │   ├── adr.md
│   │   ├── new-adapter.md
│   │   └── phase-status.md
│   └── skills/                      # project-specific skills — see §9
│       ├── ckaps-register-parser/SKILL.md
│       ├── malaysian-address-normalisation/SKILL.md
│       ├── gp-classification/SKILL.md
│       ├── pdpa-review/SKILL.md
│       └── pmcare-brand/SKILL.md
│
├── docs/
│   ├── bootstrap-prompt.md          # this file
│   ├── context/                     # THE context system — see §6/§7
│   │   ├── INDEX.md                 # machine-readable manifest
│   │   ├── architecture.md
│   │   ├── data-sources.md
│   │   ├── data-model.md
│   │   ├── entity-resolution.md
│   │   ├── malaysian-data-conventions.md
│   │   ├── compliance-pdpa.md
│   │   ├── compliance-outreach.md
│   │   ├── compliance-scraping.md
│   │   ├── environment.md
│   │   ├── conventions.md
│   │   ├── roadmap.md
│   │   ├── costs.md
│   │   ├── brand.md
│   │   ├── glossary.md
│   │   └── open-questions.md
│   ├── decisions/                   # ADRs: NNNN-slug.md
│   │   └── 0001-record-architecture-decisions.md
│   ├── runbooks/
│   │   ├── monthly-ckaps-refresh.md
│   │   ├── data-breach-notification.md
│   │   └── adapter-failure-triage.md
│   └── handoff/
│       ├── openapi.json
│       └── design-brief.md
│
├── src/grid/
│   ├── __init__.py
│   ├── config.py                    # pydantic-settings
│   ├── logging.py                   # structlog setup
│   ├── cli.py                       # typer entrypoint
│   ├── sources/                     # one module per source, uniform contract §8
│   │   ├── base.py                  # SourceAdapter ABC + SourceMeta
│   │   ├── ckaps.py                 # PRIMARY  — Act 586 register PDFs
│   │   ├── google_places.py         # PRIMARY  — enrichment + recency
│   │   ├── socso_panel.py           # PRIMARY  — leading indicator
│   │   ├── osm_overpass.py          # SECONDARY
│   │   ├── competitor_panels.py     # SECONDARY — diffable panel lists
│   │   ├── health_directories.py    # SECONDARY
│   │   ├── job_boards.py            # LEADING  — earliest signal
│   │   ├── chain_news.py            # LEADING
│   │   └── social_signals.py        # LEADING
│   ├── ingest/
│   │   ├── snapshots.py             # immutable timestamped snapshot store
│   │   └── differ.py                # new vs newly-listed-but-old
│   ├── normalise/
│   │   ├── names.py                 # Klinik/Poliklinik/Sdn Bhd handling
│   │   ├── addresses.py             # Jalan/Jln, postcode→state
│   │   ├── phones.py                # → +60 E.164
│   │   └── states.py                # canonical state names + variants
│   ├── resolve/
│   │   ├── blocking.py
│   │   ├── matching.py              # rapidfuzz scoring
│   │   └── clusters.py              # golden-record assembly
│   ├── classify/
│   │   └── gp_filter.py             # GP vs dental/specialist/aesthetic
│   ├── enrich/
│   │   ├── geocode.py
│   │   └── recency.py               # signal fusion → confidence score
│   ├── panel/
│   │   └── suppression.py           # PMCare panel matching
│   ├── score/
│   │   └── priority.py             # engagement ranking
│   ├── db/
│   │   ├── models.py
│   │   ├── session.py
│   │   └── migrations/              # alembic
│   ├── api/
│   │   ├── main.py
│   │   ├── routers/
│   │   ├── schemas.py
│   │   └── deps.py
│   └── export/
│       └── xlsx.py                  # PNM-facing workbook
│
├── scripts/
│   ├── check_context.py             # THE staleness gate — see §7
│   ├── fetch_ckaps_manual.md        # human procedure, not automation
│   └── seed_synthetic.py
│
├── tests/
│   ├── conftest.py
│   ├── fixtures/                    # SYNTHETIC ONLY
│   ├── unit/
│   ├── integration/
│   └── test_context_hygiene.py      # asserts check_context.py passes
│
└── data/                            # GITIGNORED ENTIRELY
    ├── raw/
    ├── interim/
    └── exports/
```

## 6. The CLAUDE.md contract

`CLAUDE.md` is a **router, not a manual.** It is read on every session; bloat there costs every future turn.

### Hard rules

1. **≤150 lines, ≤1,200 words.** Enforced by `scripts/check_context.py`, which fails the pre-commit hook.
2. Only four things live inline: (a) one-paragraph mission, (b) current phase + next milestone, (c) the **hard guardrails** from §2 in compressed form, (d) the pointer table to `docs/context/*.md`.
3. **Everything else is a pointer.** If a section exceeds ~20 lines, extract it to a scoped file in `docs/context/`, add a row to the pointer table, add it to `INDEX.md`, and delete the body from `CLAUDE.md`.
4. **When splitting, never trim signal to fit the budget.** Move it. A guardrail lost to a line count is a compliance incident waiting to happen.
5. The pointer table has a **"Load when"** column so you know which files to read for the task at hand rather than reading all of them.

(The full CLAUDE.md skeleton from the brief is realised as the actual `CLAUDE.md` at
the repo root.)

## 7. Anti-staleness system — build this in the first session

This is a stated priority. Documentation drift is the default failure mode of agent-assisted projects, so it gets real machinery, not good intentions.

### 7.1 Front matter on every context file

```markdown
---
title: Data Sources
owner: thiran
last_verified: 2026-08-06
verify_by: 2026-11-06          # max 90 days out
covers_paths:                   # code this doc describes
  - src/grid/sources/**
external_sources:               # things that change outside the repo
  - name: MOH CKAPS register
    url: https://hq.moh.gov.my/medicalprac/senarai-klinik-perubatan-swasta/
    checked: 2026-08-06
status: current                 # current | needs-review | stale
---
```

### 7.2 `scripts/check_context.py` — the gate

Single Python script, no non-stdlib deps beyond `pyyaml`, cross-platform, exits non-zero on failure with a clear per-finding report. Checks:

| # | Check | Severity |
|---|---|---|
| 1 | `CLAUDE.md` ≤150 lines and ≤1,200 words | **fail** |
| 2 | Every `docs/context/*.md` has valid, complete front matter | **fail** |
| 3 | Every `docs/context/*.md` appears in `CLAUDE.md`'s pointer table **and** in `INDEX.md` — no orphans | **fail** |
| 4 | Every pointer-table path actually exists — no dead links | **fail** |
| 5 | `verify_by` is not in the past | **fail** |
| 6 | `verify_by` within 14 days | warn |
| 7 | **Drift detection:** for each context file, `git log --since=<last_verified> -- <covers_paths>` returns commits → the code moved but the doc did not | **fail** |
| 8 | No context file exceeds 300 lines (split it) | warn |
| 9 | Every `src/grid/sources/*.py` adapter is documented in `data-sources.md` | **fail** |
| 10 | Every adapter declares `SourceMeta` with a legal basis | **fail** |
| 11 | ADR numbering is contiguous, no duplicates | warn |
| 12 | `.env.example` covers every var read by `config.py` | **fail** |
| 13 | No forbidden strings in tracked files (candidate IC/NRIC patterns, `+60` mobiles in non-test files, `.xlsx`/`.csv` at repo root) | **fail** |

Add `--fix` to auto-bump trivially resolvable items (e.g. regenerate `INDEX.md` from front matter) and `--report` for a markdown summary.

### 7.3 Enforcement layers

1. **Pre-commit** (`.pre-commit-config.yaml`): a `local` hook running `python scripts/check_context.py`, alongside `ruff`, `ruff-format`, `mypy`, and a `detect-private-key` / large-file guard. Written in Python so it works in PowerShell.
2. **CI** (`.github/workflows/ci.yml`): same script + tests on push and PR.
3. **Test** (`tests/test_context_hygiene.py`): asserts the checker passes, so `pytest` alone catches drift.
4. **Claude Code hooks** (`.claude/settings.json`): a `SessionStart` hook running `python scripts/check_context.py --report` so drift is visible at the top of every session, and a `Stop` hook running the same check so it surfaces before work is considered finished. **Verify current hook event names against the Claude Code hooks documentation before writing the config** — do not guess the schema. If an event name cannot be verified, implement only the ones you can confirm and note the rest in `open-questions.md`.
5. **Slash commands** in `.claude/commands/`:
   - `/context-audit` — run the checker, summarise findings, propose fixes.
   - `/context-update` — given a diff or task description, identify which context files must change, edit them, bump `last_verified`.
   - `/adr <title>` — scaffold the next-numbered ADR.
   - `/new-adapter <source>` — scaffold a source adapter + tests + a `data-sources.md` row + a `compliance-scraping.md` entry, all in one go, so no adapter can be added without its docs.
   - `/phase-status` — read `roadmap.md`, report progress against acceptance criteria.

### 7.4 Split protocol

When a context file exceeds 300 lines or covers more than one concern:

1. Create the new scoped file with full front matter.
2. Move — never summarise away — the content.
3. Leave a one-line pointer in the original if cross-reference is useful.
4. Add rows to `CLAUDE.md`'s table and `INDEX.md`.
5. Run `check_context.py`.
6. Record the split in the commit message.

Prefer many small, sharply scoped files over few large ones. `data-sources.md` will be the first to outgrow itself — plan for `data-sources/` becoming a directory with one file per source, and make the checker tolerate both shapes.

## 8. Source adapter contract

Every source implements the same interface so orchestration, testing, and compliance auditing are uniform.

```python
class SourceMeta(BaseModel):
    key: str  # "ckaps"
    display_name: str
    verdict: Literal["primary", "secondary", "leading_indicator", "low_value"]
    access_mode: Literal["manual_download", "api", "scrape", "purchased"]
    legal_basis: str  # REQUIRED. ToS/robots position + why this mode is compliant.
    robots_allows_automation: bool
    typical_detection_lag_days: tuple[int, int]
    exposes_personal_data: bool
    gp_filter_available: bool  # does the source itself distinguish GP?
    refresh_cadence: str
    cost_note: str  # "free" | "requires business owner sign-off: ..."


class SourceAdapter(ABC):
    meta: SourceMeta

    def fetch(self, run_id: str) -> SnapshotRef: ...  # raw → data/raw/, immutable
    def parse(self, snap: SnapshotRef) -> Iterable[RawClinicRecord]: ...
    def health_check(self) -> HealthStatus: ...  # is the source still shaped as expected?
```

Notes:
- `ckaps.py`'s `fetch` **does not download** — it validates that a human-placed snapshot exists in `data/raw/ckaps/<date>/` and raises an actionable error pointing at `docs/runbooks/monthly-ckaps-refresh.md` if not.
- `health_check` matters: these sources change layout without warning. A failing health check should alert, not silently produce zero rows.
- Parse CKAPS PDFs with **`pdfplumber`** (`extract_tables()` first, `extract_text()` fallback). Run `pdfinfo`/`pdffonts` equivalents up front to confirm a text layer exists; if a state list turns out to be scanned with no fonts, do not silently return nothing — flag it and note OCR as a follow-up. The register exposes clinic name, full address, postcode, state, scope (`Klinik Umum` vs specialist), and sometimes a registration number. **The scope column is the single best GP filter available anywhere — treat it as the ground truth other sources are calibrated against.**

## 9. Skills

### Public skills — invoke, don't reinvent

| Skill | Use for |
|---|---|
| `pdf-reading` | CKAPS register PDF inspection and extraction. Read this before writing `ckaps.py`. |
| `pdf` | Only if GRID ever needs to *produce* or fill PDFs. |
| `xlsx` | PNM-facing clinic workbook exports (`src/grid/export/xlsx.py`). |
| `docx` | PDPA governance docs, provider advisories, memos. |
| `pptx` | Steerco / insurer decks. Apply PMCare brand tokens. |
| `frontend-design` | Only for the Claude Design handoff brief — not for building UI here. |
| `file-reading` | Reading any uploaded artefact whose contents aren't already in context. |

### Project skills to author in `.claude/skills/`

Each is a directory with a `SKILL.md` carrying `name` and `description` front matter. Keep descriptions trigger-rich so they fire without being asked.

1. **`ckaps-register-parser`** — the CKAPS PDF layout, per-state quirks, the scope-column taxonomy, snapshot naming, known parsing failure modes, and how to diff two snapshots.
2. **`malaysian-address-normalisation`** — Jalan/Jln, Lorong/Lrg, Persiaran/Psn, Taman, block/unit and "Tingkat Bawah"/"Ground Floor" forms; the 5-digit postcode → state/district mapping; state-name variants (Pulau Pinang / P. Pinang / Penang; Melaka / Malacca; WP KL / Kuala Lumpur / K.L.); shoplot addressing.
3. **`gp-classification`** — decision rules for GP vs dental vs specialist vs physio vs lab vs aesthetics-only, keyword lists in both Bahasa Malaysia and English, and the rule that CKAPS scope overrides all heuristics.
4. **`pdpa-review`** — a checklist to run before any change that touches personal data: which fields, lawful basis, retention, access control, whether the field belongs in the personal table, breach-notification implications.
5. **`pmcare-brand`** — Arial throughout; Navy Blue `#1F4E79` primary, Teal `#16A085` secondary, Dark Gray `#2D3748` accent, header Blue `#2C5282`; table header rows navy with white bold text; status Green `#10B981` / Amber `#F59E0B` / Red `#EF4444` / Blue `#3B82F6`; decks open with a branded title slide (logo, title, date). Also mirror these tokens into `docs/context/brand.md`.

## 10. MCP servers

**Principle: native tools first.** Claude Code already reads/writes files, runs commands, and searches. Only add an MCP server where it removes real friction. Every server added is context overhead and a supply-chain consideration.

**Before configuring any of these, verify the current package name, install command, and config schema against the official documentation.** MCP server names, ownership, and availability shift; several previously-bundled reference servers have moved or been archived. Do not write a config from memory. If you cannot verify one, skip it and log it in `open-questions.md`.

### Tier 1 — configure now

| Server | Why for GRID |
|---|---|
| **Postgres** (or a Postgres-capable DB server) | Inspect the warehouse, sanity-check entity-resolution output, and validate migrations without writing throwaway scripts. Configure **read-only** against a dev database. Highest practical value here. |
| **Playwright** (Microsoft's official browser MCP) | JS-rendered directories (GetDoc, DoctorOnCall) and inspecting page structure when writing scrapers. Interactive investigation, not production scraping — production uses the pinned `playwright` library in code. |
| **Fetch** | Retrieving public pages/docs during development. Respect the same robots/ToS guardrails as production code — an MCP server is not an exemption. |
| **Filesystem** | Only if you need scoped access outside the repo root (e.g. a Downloads folder where CKAPS PDFs land). Scope it tightly to that one directory. |

### Tier 2 — add when the relevant phase starts

| Server | Why |
|---|---|
| **Google Maps** | Places enrichment during Phase 1 exploration. **Storage guardrail still applies** — persist `place_id` only. Production calls go through `src/grid/enrich/`, not the MCP server, so quota and caching stay controlled. |
| **GitHub** | Issues/PRs for phase tracking, if the team works in GitHub. |
| **Git** | Only if native git-via-bash proves insufficient — usually it doesn't. |
| **Sequential thinking** | Entity-resolution and dedup design reasoning. Optional. |
| **Slack** | Phase 3: notify PNM of the weekly new-clinic queue. Only after the API exists. |

### Explicitly do not configure

- Anything that would automate access to **`hq.moh.gov.my`** or **SSM**. The guardrails in §2 apply to MCP tools identically.
- Broad-scope filesystem servers pointed at the user's home directory.

Record final MCP choices, scopes, and rationale in `docs/context/environment.md`, and the "why not" list as an ADR.

## 11. Data model

Design in `docs/context/data-model.md` before writing migrations. Every column is annotated `pdpa_class: business | personal`.

Core tables:

- **`clinic`** — golden record. `clinic_id` (internal UUID), `name_canonical`, `name_variants[]`, `address_canonical`, `postcode`, `city`, `district`, `state` (canonical enum), `geom` (PostGIS Point, SRID 4326), `phone_e164`, `email_business`, `website`, `scope` (`gp` | `gp_with_interest` | `specialist` | `excluded`), `ckaps_reg_no`, `google_place_id`, `first_seen_at`, `opened_estimate`, `opened_confidence`, `status`.
- **`clinic_source_record`** — one row per source sighting: `source_key`, `snapshot_id`, `raw_payload` (JSONB), `observed_at`, `match_confidence`, `clinic_id`. Full provenance; never overwrite.
- **`practitioner`** — **personal data, restricted.** `name`, `mmc_no`, `clinic_id`, `lawful_basis`, `retention_until`, `source_key`. Not in default API responses.
- **`recency_signal`** — `clinic_id`, `signal_type` (`job_posting` | `socso_panel_add` | `first_google_review` | `grand_opening_post` | `ckaps_new_registration` | `chain_announcement`), `signal_date`, `source_url`, `weight`.
- **`panel_membership`** — `clinic_id`, `panel_owner` (`pmcare` | `socso` | named competitor), `status`, `observed_at`. Drives suppression and prioritisation.
- **`snapshot`** — `snapshot_id`, `source_key`, `taken_at`, `path`, `checksum`, `row_count`. Immutable; the basis of diffing.
- **`engagement`** — `clinic_id`, `queue` (`a_new_opening` | `b_existing_not_on_panel`), `priority_score`, `assigned_to`, `status`, `contact_attempts[]`, `consent_state`, `opt_out_at`.
- **`kpi_month`** — engaged counts per month vs the 40–60 target.

Deduplication and diffing rules:

- Normalise before matching: name (strip/standardise `Klinik`, `Poliklinik`, `Klinik Perubatan`, `Medical Centre`, `Clinic & Surgery`, `Sdn Bhd`), address, phone → `+60` E.164 via `phonenumbers`.
- Block on `postcode`, then `phone_e164`, then normalised-name trigrams. Score with `rapidfuzz` token-set ratio + Jaro-Winkler; combine with address and phone agreement. Auto-merge above a high threshold, queue a human review band in the middle, never silently merge in the ambiguous band.
- **A record is "genuinely new" only if absent from prior CKAPS snapshots AND corroborated by at least one `recency_signal`.** Otherwise it is *newly listed but pre-existing* → Queue B, not Queue A.
- **Relocations and rebrands are updates, not new market entrants.** Detect via phone or practitioner continuity across a changed address/name. This is common and will inflate your new-opening count if unhandled.

## 12. Phased build

Do not start Phase 2 until Phase 1's acceptance criteria pass. Keep `roadmap.md` as the live source of truth.

### Phase 1 — Authoritative spine (target: weeks 1–4)

Scaffold; `check_context.py` + hooks + pre-commit + CI green; Postgres/PostGIS up with migrations; CKAPS snapshot ingester, parser, differ; `Klinik Umum` GP filter; normalisation modules; Google Places enrichment with storage guardrails; PMCare panel loader + suppression; entity resolution v1; XLSX export.

**Acceptance:** a real CKAPS snapshot for **all states including Sabah and Sarawak** parses to a normalised table with a measured field-completeness report; two snapshots diff correctly and separate genuinely-new from newly-listed; a Queue B list of GP clinics not on the PMCare panel exports to a branded XLSX; suppression false-positive rate measured on a hand-labelled sample of ≥100 pairs; `check_context.py` exits 0.

### Phase 2 — Leading indicators and volume (weeks 5–8)

SOCSO panel diff; competitor panel diff; job-board adapter (the earliest signal — clinics hire before opening); chain-news and social-signal adapters; recency-signal fusion into `opened_confidence`; priority scoring; scheduled runs; adapter health checks and alerting.

**Acceptance:** ≥30 candidate new-opening clinics surfaced in a calendar month with evidence links; Queue A + Queue B combined sustainably exceeds 60/month; precision measured on a manually verified sample of ≥50 Queue A records; every adapter has a passing health check and a `data-sources.md` row.

### Phase 3 — API, exports, governance, handoff (weeks 9–12)

FastAPI service (queue endpoints, clinic detail, filters, KPI summary, engagement status updates, consent/opt-out); role-based access separating business from personal data; audit logging; `openapi.json`; the Claude Design brief; PDPA governance pack; breach-notification and adapter-triage runbooks; `costs.md` with spend estimates flagged for sign-off.

**Acceptance:** API serves both queues with pagination, filtering by state/recency/panel status/score; personal data requires elevated scope and access is logged; opt-out is permanently honoured and provably suppresses; outreach send capability exists but is **disabled by config and documented as requiring compliance sign-off**; handoff artefacts complete.

## 13. Conventions

- **Commits:** Conventional Commits (`feat(sources): add SOCSO panel adapter`). Reference the ADR when a decision is embedded.
- **Style:** `ruff` (lint + format), `mypy` strict on `src/`, Google-style docstrings, type hints everywhere.
- **Logging:** `structlog`, JSON in production. **Never log PII or full raw payloads containing personal data** — log record counts and IDs.
- **Tests:** `pytest`; synthetic fixtures only; every adapter gets a parse test against a redacted/synthetic sample; every normalisation rule gets table-driven cases; entity resolution gets a labelled pair set with tracked precision/recall.
- **Errors:** fail loudly and specifically. A source returning zero rows is a **failure**, not an empty success.
- **Secrets:** `.env` only, `pydantic-settings`, never in code, `.env.example` always current.

## 14. First session — do these in order

1. Read this brief fully. Read `/mnt/skills/public/pdf-reading/SKILL.md` before touching CKAPS parsing.
2. `git init` if needed; create `.gitignore`, `.gitattributes`, `README.md`.
3. Create the full directory tree from §5 with placeholder `README.md`s.
4. Write `CLAUDE.md` from the §6 skeleton. Verify it is under budget.
5. Write every `docs/context/*.md` with complete front matter. They may be thin — but they must exist, be linked, and be honest about what is not yet known. Seed `open-questions.md` from anything in this brief you could not verify.
6. Write `docs/context/INDEX.md`.
7. Write `scripts/check_context.py` with all 13 checks. Run it. Fix everything until it exits 0.
8. Wire `.pre-commit-config.yaml`, `tests/test_context_hygiene.py`, and CI. Verify the hook actually blocks a deliberately over-length `CLAUDE.md`, then revert the test.
9. Verify Claude Code hook event names against current documentation, then write `.claude/settings.json`. Write the five slash commands.
10. Author the five project skills in `.claude/skills/`.
11. `pyproject.toml` + `uv sync`; `compose.yaml`; bring Postgres/PostGIS up; Alembic init.
12. ADR `0001` (record ADRs) and `0002` (why APScheduler over Prefect for now).
13. Verify and configure Tier 1 MCP servers. Record scopes and rationale.
14. **Then** start Phase 1 code, beginning with `sources/base.py` and `sources/ckaps.py`.

Stop and report after step 13 with a summary and anything blocked. Do not run ahead into Phase 1 implementation without checking in.

## 15. Things to ask rather than assume

Seed these into `open-questions.md` and raise them with me:

- **PMCare's current panel size and the format of the panel extract** — this sets the exact Queue B size and the suppression schema. Blocking for Phase 1.
- Whether Google Maps Platform billing is already provisioned, and the approved monthly ceiling in RM.
- Whether PMCare has an existing DPO and PDPA processing register that GRID must register with.
- Which competitor panels PMCare is comfortable diffing, given the commercial sensitivity.
- Whether the PNM team's existing CRM must be the system of record, with GRID feeding it rather than owning `engagement`.
- Confirmation of the current gross-new-registration vs closure split from MOH (research found only an older 2014–2017 breakdown).
- Whether Sabah and Sarawak need separate handling for state health department processes.
- The commencement status of CMA s.233A at build time — check, don't assume.
