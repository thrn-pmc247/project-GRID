---
title: Data Sources
owner: thiran
last_verified: 2026-08-12
verify_by: 2026-11-10
covers_paths:
  - src/grid/sources/**
  - src/grid/ingest/**
external_sources:
  - name: MyGeoCKAPS ArcGIS REST (CKAPS registry on MyGOS)
    url: https://mygos.mygeoportal.gov.my/gisserver/rest/services/KKM/FASILITI_KESIHATAN_SWASTA_PUBLIC/MapServer
    checked: 2026-08-12
  - name: ProtectHealth clinic finder (MADANI / PeKa B40)
    url: https://kelayakan-spm.protecthealth.com.my/find-clinics
    checked: 2026-08-12
  - name: MOH CKAPS register PDFs (historical baseline only)
    url: https://hq.moh.gov.my/medicalprac/senarai-klinik-perubatan-swasta/
    checked: 2026-08-12
status: current
---

# Data sources

One row per adapter. `scripts/check_context.py` fails if a module exists in
`src/grid/sources/` without a row here. Per-source ToS/robots detail lives in
`compliance-scraping.md`. **No adapters are implemented yet.**

> **Revised 2026-08-12 (ADR 0004).** The spine moved from parsing stale CKAPS register
> PDFs to querying the live MyGeoCKAPS geospatial service. **The new spine is not yet
> verified** — see "Verification gate" below. Do not build against it until the gate
> clears.

## Hierarchy

| Rank | Source (module) | Role | Verdict | Access mode | Legal basis (summary) | Detection lag | GP filter at source? | Personal data? | Cadence |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `mygeockaps` — MyGeoCKAPS layer 5 (Klinik Perubatan Swasta) | Authoritative GP universe + geocoding | **primary (gated)** | api (ArcGIS REST) | **UNRESOLVED** — `mygos.mygeoportal.gov.my` returns ROBOTS_DISALLOWED; whether low-volume querying of a documented public REST endpoint is acceptable is undecided. No adapter ships until settled (open q. 16) | unknown — depends on GIS update cadence (open q. 17) | **Yes — layer selection.** Dental/hospital/specialist facilities sit in separate layers | Unknown — check for practitioner names (open q. 19) | monthly (target) |
| 2 | `protecthealth` — MADANI / PeKa B40 clinic finder | Market-entry signal; a clinic joining a payer panel wants panel business | **primary** | scrape (paginated, `?state_code=…&page=N`) | Public clinic finder; ProtectHealth ToS **not yet assessed** | weeks | **Yes — scheme rule.** Requires registration as "Klinik Perubatan Swasta"; specialist clinics excluded | No (clinic-level listing) | monthly |
| 3 | `job_boards` — clinic job ads (JobStreet, Indeed) | **Earliest signal — clinics hire before opening** | leading_indicator | scrape/api (TBD) | Anti-scraping ToS common — verify per board; prefer official APIs | earliest of any source | Weak (ad-text heuristics) | Sometimes (contact person) | weekly |
| 4 | `google_places` — Places API | Contact enrichment: phone, hours, website, review recency | **primary (reduced role)** | api | Paid API under Google Maps Platform ToS; persist `place_id` only, refresh on read | days–weeks | Partial (types + name heuristics) | No | weekly |
| 5 | `perkeso_panel` — PERKESO/SOCSO panel search | Secondary market-entry signal | secondary (**downgraded**) | interactive portal search | Portal moved from static PDF lists to interactive "Carian Panel"; sits behind an F5 WAF that rejected automated requests 2026-08-12 | weeks | Partial | **Yes — listings carry doctors' names** → segregated table | monthly |
| 6 | `competitor_panels` — published competitor/insurer panel lists | Queue B prioritisation, competitive intel | secondary | scrape (diffable lists) | Publicly published lists only; per-target robots/ToS check before adding any target | weeks–months | Partial | No | monthly |
| 7 | `kkmnow` — KKMNOW / data.gov.my | Base rates, KPI calibration | reference | **api** — `api.data.gov.my`; parquet via `storage.data.gov.my` | Open data, CC BY 4.0 | n/a | n/a | No | as needed |
| 8 | `osm_overpass` — OpenStreetMap Overpass | Cross-check only | secondary (**downgraded**) | api | ODbL-licensed open data; Overpass usage policy (rate limits) | months | Partial (amenity/healthcare tags) | No | monthly |
| 9 | `health_directories` — GetDoc, DoctorOnCall, etc. | Panel-membership tagging | secondary | scrape | Per-directory robots/ToS check required before build | weeks | Partial | Sometimes (doctor names — personal table rules apply) | monthly |
| 10 | `ckaps_pdf` — MOH CKAPS register PDFs | **Historical baseline only** | **demoted from primary** | manual_download | hq.moh.gov.my returns ROBOTS_DISALLOWED; human downloads per `docs/runbooks/monthly-ckaps-refresh.md` | **years — 2022/2023 vintage** | Yes — scope column (`Klinik Umum`) | Sometimes (person-in-charge names — strip at parse) | ad hoc |

## Hard exclusions

- **`hq.moh.gov.my` is never crawled.** Manual download only.
- **SSM (MyData / e-Info / EzBiz) is never scraped.** Paid per-document or licensed
  reseller only, and only if a concrete need arises (none identified yet).
- **`mygos.mygeoportal.gov.my` is not fetched by any automated tooling** — including
  MCP servers, WebFetch and dev-time browsing — until open question 16 is answered.

## MyGeoCKAPS layer map

Facility type is separated *by layer*, which is why the GP classification problem
largely dissolves (ADR 0004).

| ID | Layer | Disposition |
|---|---|---|
| 0 | Pusat Hemodialisis Swasta | exclude |
| 1 | Hospital Swasta | exclude |
| 2 | Bank Darah Swasta | exclude |
| 3 | Hospis Swasta | exclude |
| 4 | Klinik Pergigian Swasta | **exclude — dental** |
| **5** | **Klinik Perubatan Swasta** | **← THE TARGET** |
| 6 | Pusat Ambulatori Swasta | exclude |
| 7 | Pusat Kesihatan Mental Masyarakat Swasta | exclude |
| 8 | Rumah Bersalin Swasta | exclude |
| 9 | Rumah Jagaan Kejururawatan Psikiatri Swasta | exclude |
| 10 | Premis Jagaan Kesihatan Swasta Gabungan | **review — combined premises** |
| 11 | Rumah Jagaan Kejururawatan | exclude |
| 12 | Data Asas | reference |
| 15 | Hospital Swasta dengan Kelulusan Borang 2 | exclude |
| 16 | Pusat Hemodialisis Swasta dengan Kelulusan Borang 2 | exclude |

### Service capabilities (from published metadata — not directly inspected)

- Query formats JSON, geoJSON, PBF
- `MaxRecordCount: 2000` → paginate with `resultOffset` / `resultRecordCount`
- Supports Advanced Queries, Statistics, OrderBy, Distinct
- `esriGeometryPoint`, Spatial Reference **4326 (WGS84)** — every facility carries lat/long
- Layer 5 national extent XMin 99.72, YMin 1.17, XMax 119.01, YMax 6.89 — covers
  Peninsular **and** East Malaysia
- Field names glimpsed on sibling layers: `ID_UNIK_PHS`, `STATUS_OPERASI`, `NEGERI`, `BIL`

## Verification gate — before any `mygeockaps` code

Direct inspection was impossible: the host returns `ROBOTS_DISALLOWED` to automated
fetching and guardrail 13 makes that binding on tooling. Everything above about the
service is **metadata-derived, not confirmed**. A human must check, in a browser:

1. Full layer 5 field list — above all **whether a registration/approval date field
   exists** (open q. 14). Its absence changes how Queue A works entirely.
2. Layer 5 record count vs MOH's 11,067 registered private medical clinics, 2024
   (open q. 15).
3. `robots.txt` and the access position (open q. 16).

Freshness/cadence (17), phone numbers (18) and practitioner names (19) must be settled
before the schema is finalised.

## ProtectHealth notes

- MADANI has run as a **district-limited pilot** (reported ~10 selected districts), so
  coverage is partial, not national — verify current district coverage before sizing.
- Panel growth (750+ clinics August 2023 → a reported 1,205 in 2026) and the district
  figure are **second-hand from secondary Malaysian news sources**, not ProtectHealth
  primary material. Do not quote either as fact (guardrail 10).
- Value is behavioural, not merely existential: a clinic that has just joined a
  government panel has demonstrated it wants panel business — a warmer lead than a
  clinic that merely exists in a register.

## CKAPS PDF notes (historical baseline path only)

Retained for back-fill and cross-checking, not for detection. If ever parsed: use
`pdfplumber` (`extract_tables()` first, `extract_text()` fallback); verify a text layer
exists up front and **flag scanned state lists loudly**, never silently zero rows. The
scope column (`Klinik Umum` vs specialist) remains a useful calibration set for any
heuristic GP classifier applied to non-layered sources.
