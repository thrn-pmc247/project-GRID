# Project GRID — Agent Context Router

> **Read this file fully every session. Load linked context files on demand per the table below.**
> Last verified: 2026-08-17 · Budget: ≤150 lines / ≤1,200 words (enforced by `scripts/check_context.py`)

## Mission

PMCare is a Malaysian TPA/MCO; its Provider Network Management (PNM) team must engage
40–60 new GP clinics per month. GRID discovers newly opened and newly registered private
GP clinics across all Malaysian states and federal territories (incl. Sabah & Sarawak),
normalises and deduplicates them, suppresses clinics already on the PMCare panel, and
serves a ranked engagement queue via an API. Two queues are first-class: **Queue A** —
new openings (time-sensitive, highest conversion) and **Queue B** — existing registered
GP clinics not yet on panel (the volume buffer that guarantees the KPI in slow months).
GP / primary care only.

## Current state

- Phase: 1 of 3 — Authoritative spine. **Incumbent side built** (2026-08-17): the PR001
  provider master loads bronze→staging→core with reference tables, a coordinate gate, a
  REMARKS miner and PDPA controls. Discovery side not started.
- Two spines, two roles: **MyGeoCKAPS layer 5 = discovery** (ADR 0004, still current);
  **PR001 = the incumbent network and the resolution target** (ADR 0005).
- `PROVIDER_CODE` and `ROW_GUID` are the only safe PR001 keys. `MIX_ROW_ID` collides on
  15 rows — never join, index or constrain on it.
- Next milestone: `sources/base.py`. The `mygeockaps` adapter is **gated** on open
  questions 14–16 (field list / record count / access) — do not write it before they clear
- Status detail: `docs/context/roadmap.md`

## Hard guardrails — never violate

1. Never crawl hq.moh.gov.my (ROBOTS_DISALLOWED). Its register PDFs are a manual,
   historical-baseline path only (`docs/runbooks/monthly-ckaps-refresh.md`). Never fetch
   mygos.mygeoportal.gov.my by any automated means (WebFetch, MCP, dev browsing) until
   open question 16 settles access — human browser inspection only.
2. Never scrape SSM (MyData / e-Info / EzBiz). Paid/licensed access only.
3. Google Places: persist `place_id` only. Never cache other Places content; refresh on read.
4. Segregate business data from practitioner personal data at schema level (PDPA 2010 as
   amended 2024). A sole proprietor's dual-use mobile is personal data.
5. Never commit real clinic data, PII, exports or secrets. `data/` is gitignored entirely.
6. No mass automated WhatsApp/email outreach. Consent-first, phone-first; any send
   capability stays behind `GRID_OUTREACH_SEND_ENABLED=false` pending compliance sign-off.
7. GP clinics only. Exclude dental, specialist, physio, labs, hospitals, aesthetics-only.
   MyGeoCKAPS separates these by layer — layer 5 is the target, layer 10 needs review.
8. British/Malaysian English spelling; RM for currency.
9. PMCare is a neutral TPA — never position it as insurer or treating clinician.
10. Never invent statutes, citations, registration numbers or statistics. Flag
    uncertainty in `docs/context/open-questions.md` instead of guessing.
11. Outward-facing artefacts are drafts requiring human review before sending.
12. Commercial/pricing/contract questions go to the business owner — never answered here.
13. Respect robots.txt and ToS everywhere, including dev tooling and MCP servers (they are
    not an exemption). Every adapter declares `SourceMeta` with a `legal_basis`.
14. **PR001 handling.** Extracts stay out of git (`/PR001*`, `*.parquet` — keep the root
    anchor: bare `PR001*` also matches `src/grid/pr001/`). `core.provider_outlet` is the
    incumbent network — discovery **never** writes to it; candidates go to
    `core.grid_candidate` and join via `core.outlet_candidate_link`. `QR_ENCRYPTED_TEXT`
    and `QR_FILE_PATH` are bronze-only. Coordinates are confirmatory only — just 29% of
    the master has a usable pair. Codes undeclared in `staging.ref_*` must break the
    build, never pass as NULL.

## Context map

| File | Contents | Load when |
|---|---|---|
| `docs/context/architecture.md` | Pipeline stages, adapter contract | Any structural change |
| `docs/context/data-sources.md` | Per-source access rules, verdicts, detection lag | Touching source/ingest code |
| `docs/context/data-model.md` | Tables, field-level PDPA class | Touching db or migrations |
| `docs/context/entity-resolution.md` | Blocking, matching, golden records | Touching resolve code |
| `docs/context/malaysian-data-conventions.md` | Names, addresses, states, postcodes | Touching normalise code |
| `docs/context/compliance-pdpa.md` | PDPA obligations, personal-data rules | Any personal-data handling |
| `docs/context/compliance-outreach.md` | CMA s.233A, consent-first design | Outreach features or copy |
| `docs/context/compliance-scraping.md` | Per-source ToS/robots register | Adding/changing an adapter |
| `docs/context/environment.md` | Windows/uv/Docker setup, MCP scopes | Env or dependency work |
| `docs/context/conventions.md` | Style, commits, tests, context upkeep | Writing any code |
| `docs/context/roadmap.md` | Phases, acceptance criteria, status | Planning or status |
| `docs/context/costs.md` | Spend drivers (business sign-off needed) | Cost-affecting change |
| `docs/context/brand.md` | PMCare brand tokens | Producing xlsx/docx/pptx |
| `docs/context/glossary.md` | CKAPS, PHFSA, PNM, Klinik Umum… | Unfamiliar term |
| `docs/context/open-questions.md` | Unresolved decisions for the human | Blocked or uncertain |
| `docs/decisions/` | ADRs — why things are the way they are | Revisiting a decision |
| `docs/runbooks/` | Operational procedures | Running or fixing the pipeline |
| `docs/reconciliation-pr001.md` | PR001 vs the mockup: what the data broke, measured | Touching PR001 or the data model |
| `docs/data-dictionary-pr001.yaml` | All 70 PR001 columns: type, fill, disposition | Touching a specific PR001 column |

## Definition of Done — applies to every task

1. Code + tests pass: `uv run pytest`, `uv run ruff check`, `uv run mypy src`.
2. Every affected file in `docs/context/` is updated and its `last_verified` bumped.
3. `uv run python scripts/check_context.py` exits 0.
4. Any decision with alternatives is recorded as an ADR (`/adr`).
5. Any new uncertainty is appended to `docs/context/open-questions.md`.

## Maintenance protocol

CLAUDE.md is a router, not a manual. If a section here would exceed ~20 lines, move it
to a scoped file in `docs/context/` per the split protocol in
`docs/context/conventions.md` (Context maintenance section) — **never trim guardrail
signal to fit the budget; move it**. `check_context.py` gates pre-commit, CI, pytest and
Claude Code session hooks; regenerate the manifest with `--fix` after adding files.
