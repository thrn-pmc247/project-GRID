---
title: Compliance — PDPA
owner: thiran
last_verified: 2026-08-18
verify_by: 2026-11-16
covers_paths:
  - src/grid/db/**
  - src/grid/api/**
external_sources:
  - name: PDPA 2010 (Act 709) & amendments — official portal
    url: https://www.pdp.gov.my/
    checked: 2026-08-06
status: current
---

# PDPA 2010 (as amended by the PDP (Amendment) Act 2024)

GRID processes mostly **business data**, which is the deliberate design centre of
gravity. Where personal data is unavoidable, the full regime applies.

## Classification (schema-level, from day one)

| Class | Examples | Treatment |
|---|---|---|
| **business** (default) | clinic name, business address, postcode, state, main clinic line, Act 586 reg no, website, operating hours | standard tables |
| **personal** | practitioner names, MMC numbers, personal mobiles, personal emails | `practitioner` table only: restricted access, recorded `lawful_basis`, `retention_until`, `purpose_note`; excluded from default API responses; access audited (Phase 3) |

Edge rule: a sole-proprietor clinic's "business" mobile that is also the owner's
personal mobile is **personal data**.

## 2024 amendment obligations relevant to GRID

- **DPO appointment and breach notification are mandatory and in force since
  1 June 2025.** Whether PMCare already has an appointed DPO and a processing
  register GRID must join is an open question (`open-questions.md`).
- Breach notification runbook: `docs/runbooks/data-breach-notification.md`.
  Exact notification deadlines must be verified against the current JPDP guideline
  before first reliance — flagged there and in `open-questions.md`.
- Data processor obligations now apply directly to processors; if GRID data is ever
  processed by a vendor, contracts need PDPA processor clauses.

## Engineering rules

1. Personal data never enters `clinic` or default API payloads.
2. `raw_payload` in `clinic_source_record` must be stripped of personal fields at
   parse time (practitioner names seen in CKAPS/directories go to `practitioner`
   or are dropped, not warehoused in JSONB).
3. **Never log PII or full raw payloads** — log counts and internal IDs
   (`src/grid/logging.py` docstring restates this).
4. `data/`, `.env`, exports and `*.db` are gitignored; check 13 of
   `scripts/check_context.py` scans tracked files for NRIC-like patterns and
   Malaysian mobile numbers.
5. Retention: every `practitioner` row carries `retention_until`; a scheduled purge
   job is a Phase 3 deliverable.
6. Before any change touching personal data, run the `pdpa-review` skill checklist.

## Positioning

PMCare is a neutral TPA — GRID must never present it as insurer or treating
clinician, and GRID gives no medical or legal advice. Official/outward artefacts are
drafts requiring human review.
