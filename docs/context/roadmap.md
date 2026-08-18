---
title: Roadmap
owner: thiran
last_verified: 2026-08-18
verify_by: 2026-11-16
covers_paths: []
status: current
---

# Roadmap

Live source of truth for phase status. Do not start a phase until the previous one's
acceptance criteria pass. `/phase-status` reads this file.

## Phase 0 — Bootstrap (2026-08-06) — ✅ complete

Repo scaffold, context system + `check_context.py` gate, pre-commit + CI + pytest +
Claude Code hooks, uv environment, compose.yaml, Alembic init, ADRs 0001–0003, five
slash commands, five project skills, Tier 1 MCP config.
Known blocked item: Docker Desktop not installed → database not yet brought up.

## Phase 1 — Authoritative spine (target weeks 1–4) — 🟨 in progress

> **Incumbent side landed 2026-08-17 (ADR 0005).** PMCare's provider master (PR001,
> 33,643 × 70) now loads end to end: bronze (verbatim, append-only generations,
> idempotent on SHA-256) → staging (typed, 33,643 rows, unique on `provider_code` and
> `row_guid`) → core (incumbent network, inferred chains, mined REMARKS signals) plus a
> segregated `pii` schema and a first Alembic migration covering 23 tables. This is the
> **suppression and reconciliation target**, not discovery. Detail:
> `docs/reconciliation-pr001.md`.
>
> Delivered against the acceptance list below: the first migration, the PMCare panel
> loader, and the KPI baseline. Still outstanding: everything on the discovery side.

> **Queue B shipped 2026-08-18 (ADR 0007).** The 4,550-row engagement queue and its
> branded XLSX export are derived at read time from the incumbent master — offline, no
> new tables, and blocked on nothing. This is the volume buffer that carries the 40–60
> per month KPI while Queue A stays gated behind open questions 14–16. What it is **not**
> is a list of clinics PMCare has never met: all 4,550 already hold an appointment date
> (median year 2007, against 2020 for on-panel rows), which is open question 36.

> **Rewritten 2026-08-12 (ADR 0004).** The spine is the MyGeoCKAPS ArcGIS REST service
> (layer 5), not parsed CKAPS PDFs. PDF parsing, `pdfplumber`, layout inference and OCR
> risk are all **out of Phase 1**.

Build: `sources/base.py` + `sources/mygeockaps.py` (paginated GeoJSON pull, stable-ID
differ); specialist-vs-general filter within layer 5 + layer 10 adjudication;
normalisation modules (names/phones/states); PMCare panel loader + suppression; entity
resolution v1; branded XLSX export; first Alembic migration from `data-model.md`.

**Vertical slice first — do this before building `base.py` broadly:**

```
MyGeoCKAPS layer 5 → paginated GeoJSON pull → normalise → snapshot → CSV + completeness report
```

**Acceptance:**
- [x] **PMCare panel loaded and reconciled** — PR001 lands 33,643 rows across bronze,
      staging and core with counts reconciling at every layer, a committed profile
      fixture as a drift detector, and an unknown-code guard that breaks the build on
      an undeclared code. Panel suppression can now be sourced from
      `PMCARE_PANEL_STATUS` (GP + active + on panel = 5,956).
- [x] **First Alembic migration** — 23 tables across five schemas; `upgrade head` and
      `downgrade base` both verified.
- [ ] Layer 5 pulls completely for **all states incl. Sabah & Sarawak** into a
      normalised table with a measured field-completeness report, and a record count
      reconciled against MOH's 11,067 registered private medical clinics (2024).
- [ ] Two snapshots diff correctly: genuinely-new vs newly-listed separated. *If no
      registration-date field exists, this degrades to "newly appearing in the GIS" and
      the report must say so — never present it as genuinely-new.*
- [x] **Queue B list of GP clinics not on the PMCare panel exports to branded XLSX** —
      **4,550 not on panel, of which 4,311 are a callable list**, derived at read time
      from `core.provider_outlet` with no new tables and no second migration (ADR 0007).
      13,552 GP → 10,506 active by status code (10,507 by the point-in-time rule) →
      5,957 active and on panel → 4,550 not on panel → 4,311 after routing 218 probable
      duplicates and 20 flagged rows to review and excluding 1 superseded code.
      National: Selangor 1,114 · Johor 760 · WP Kuala Lumpur 606 · Perak 398 · Pulau
      Pinang 329 · Kedah 228 · Sabah 214 · Sarawak 172 · Kelantan 169 · Negeri Sembilan
      168. Rows are **banded, not scored** — PR001 has no conversion outcome to fit
      against. The default workbook carries **no phone numbers**, so it ships ahead of
      the personal-data answers; a contact workbook sits behind a config flag defaulting
      false plus an explicit CLI flag, mobiles excluded by default. Separately, 345 GP
      providers terminated since 2024-01-01 form a win-back segment.
- [ ] Suppression false-positive rate measured on a hand-labelled sample of ≥100 pairs.
- [x] **`check_context.py` exits 0** — item **D1** of `docs/reconciliation-pr001.md` is
      cleared: `PR001_provider_master.xlsx` moved out of the repo root to `data/raw/`,
      so check 13 no longer fails on a stray root `*.xlsx`. The gate is green and stays
      a per-task Definition of Done item, not a one-off.

**Gate before any `mygeockaps` code** (ADR 0004; open questions 14–16): the layer 5
field list — above all whether a registration/approval date exists — the record count,
and the robots/access position. `sources/base.py` may be built now; the adapter may not.

Blocking input needed: MyGeoCKAPS verification (14–16), PMCare panel extract format,
Docker Desktop install (`open-questions.md`).

## Phase 2 — Leading indicators & volume (weeks 5–8) — ⬜ not started

ProtectHealth MADANI/PeKa B40 panel diff (**promoted — GP-only by scheme rule, strong
market-entry signal**); competitor panel diff; job-board adapter (earliest signal);
PERKESO panel (downgraded — WAF-blocked, and carries practitioner names); chain-news +
social-signal adapters; recency-signal fusion → `opened_confidence`; priority scoring;
scheduled runs (APScheduler); adapter health checks + alerting.

**Acceptance:**
- [ ] ≥30 candidate new-opening clinics surfaced in a calendar month with evidence links.
- [ ] Queue A + Queue B combined sustainably exceeds 60/month.
- [ ] Precision measured on a manually verified sample of ≥50 Queue A records.
- [ ] Every adapter has a passing health check and a `data-sources.md` row.

## Phase 3 — API, exports, governance, handoff (weeks 9–12) — ⬜ not started

FastAPI service (queues, clinic detail, filters, KPI summary, engagement updates,
consent/opt-out); role-based access separating business from personal data; audit
logging; `docs/handoff/openapi.json` + `design-brief.md`; PDPA governance pack;
runbooks finalised; `costs.md` estimates for sign-off.

**Acceptance:**
- [ ] API serves both queues with pagination + filters (state/recency/panel status/score).
- [ ] Personal data requires elevated scope; access is logged.
- [ ] Opt-out permanently honoured and provably suppresses.
- [ ] Outreach send exists but is disabled by config, documented as requiring
      compliance sign-off.
- [ ] Handoff artefacts complete (dashboard UI is Claude Design's, not this repo's).
