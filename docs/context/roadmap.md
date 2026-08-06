---
title: Roadmap
owner: thiran
last_verified: 2026-08-06
verify_by: 2026-11-04
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

## Phase 1 — Authoritative spine (target weeks 1–4) — ⬜ not started

Build: `sources/base.py` + `ckaps.py` (snapshot ingester, parser, differ);
`Klinik Umum` GP filter; normalisation modules (names/addresses/phones/states);
Google Places enrichment with storage guardrails; PMCare panel loader + suppression;
entity resolution v1; branded XLSX export; first Alembic migration from
`data-model.md`.

**Acceptance:**
- [ ] A real CKAPS snapshot for **all states incl. Sabah & Sarawak** parses to a
      normalised table with a measured field-completeness report.
- [ ] Two snapshots diff correctly: genuinely-new vs newly-listed separated.
- [ ] Queue B list of GP clinics not on the PMCare panel exports to branded XLSX.
- [ ] Suppression false-positive rate measured on a hand-labelled sample of ≥100 pairs.
- [ ] `check_context.py` exits 0.

Blocking input needed: PMCare panel extract format + Docker Desktop install
(`open-questions.md`).

## Phase 2 — Leading indicators & volume (weeks 5–8) — ⬜ not started

SOCSO panel diff; competitor panel diff; job-board adapter (earliest signal);
chain-news + social-signal adapters; recency-signal fusion → `opened_confidence`;
priority scoring; scheduled runs (APScheduler); adapter health checks + alerting.

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
