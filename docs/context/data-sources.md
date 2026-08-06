---
title: Data Sources
owner: thiran
last_verified: 2026-08-06
verify_by: 2026-11-04
covers_paths:
  - src/grid/sources/**
  - src/grid/ingest/**
external_sources:
  - name: MOH CKAPS private clinic register
    url: https://hq.moh.gov.my/medicalprac/senarai-klinik-perubatan-swasta/
    checked: 2026-08-06
status: current
---

# Data sources

One row per adapter. `scripts/check_context.py` fails if a module exists in
`src/grid/sources/` without a row here. Per-source ToS/robots detail lives in
`compliance-scraping.md`. **No adapters are implemented yet** — Phase 1 starts with
`base.py` + `ckaps.py`.

| Source (module) | Verdict | Access mode | Legal basis (summary) | Detection lag | GP filter at source? | Personal data? | Cadence |
|---|---|---|---|---|---|---|---|
| `ckaps` — MOH CKAPS register PDFs (Act 586) | **primary** | manual_download | hq.moh.gov.my returns ROBOTS_DISALLOWED; a human downloads the published register PDFs per `docs/runbooks/monthly-ckaps-refresh.md`; parsing is local | ~30–90 days after registration | **Yes — scope column (`Klinik Umum`) is ground truth** | Sometimes (person-in-charge names — strip at parse) | monthly |
| `google_places` — Places API | **primary** | api | Paid API under Google Maps Platform ToS; persist `place_id` only, refresh on read | days–weeks after opening | Partial (types + name heuristics) | No | weekly |
| `socso_panel` — SOCSO/PERKESO panel clinic list | **primary** | scrape/manual (TBD in Phase 2) | Public panel listing; access mode to be confirmed against robots/ToS before build | weeks (clinics join SOCSO panel early — leading indicator) | Partial | No | monthly |
| `osm_overpass` — OpenStreetMap Overpass | secondary | api | ODbL-licensed open data; Overpass usage policy (rate limits) | months | Partial (amenity/healthcare tags) | No | monthly |
| `competitor_panels` — published competitor/insurer panel lists | secondary | scrape (diffable lists) | Publicly published lists only; per-target robots/ToS check before adding any target | weeks–months | Partial | No | monthly |
| `health_directories` — GetDoc, DoctorOnCall, etc. | secondary | scrape | Per-directory robots/ToS check required before build; rate-limited, descriptive UA | weeks | Partial | Sometimes (doctor names — personal table rules apply) | monthly |
| `job_boards` — clinic job ads (Jobstreet etc.) | **leading_indicator** | scrape/api (TBD) | Anti-scraping ToS common — verify per board; prefer official APIs | **earliest signal — clinics hire before opening** | Weak (ad-text heuristics) | Sometimes (contact person) | weekly |
| `chain_news` — chain-clinic expansion announcements | leading_indicator | scrape (RSS/news) | Public press/news; standard robots respect | weeks before opening | Partial | No | weekly |
| `social_signals` — grand-opening posts etc. | leading_indicator | api/scrape (TBD) | Platform ToS highly restrictive — Phase 2 design decides what is feasible; may be manual-assisted | days–weeks | Weak | Possible — PDPA review required | weekly |

## Hard exclusions

- **`hq.moh.gov.my` is never crawled.** Manual download only.
- **SSM (MyData / e-Info / EzBiz) is never scraped.** Paid per-document or licensed
  reseller only, and only if a concrete need arises (none identified yet).

## CKAPS parsing notes

- Parse with `pdfplumber` (`extract_tables()` first, `extract_text()` fallback).
- Verify a text layer exists up front (pdfplumber page objects / `pypdf`); a scanned
  state list must be **flagged loudly**, never silently zero rows. OCR is a noted
  follow-up, not silently skipped.
- Register exposes: clinic name, full address, postcode, state, scope
  (`Klinik Umum` vs specialist), sometimes an Act 586 registration number.
- The scope column calibrates every other source's GP classifier.
