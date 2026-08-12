# 0004 — MyGeoCKAPS REST API replaces CKAPS PDF parsing as the Phase 1 spine

Date: 2026-08-12 · Status: accepted — **implementation gated, see Gate below**

Supersedes the source plan in ADR-less Phase 0 scaffolding and the `ckaps` rows in
`docs/context/data-sources.md` as written on 2026-08-06.

## Context

Phase 1 was designed around parsing the MOH CKAPS "Senarai Klinik Perubatan Swasta"
register PDFs: a manual monthly download (`docs/runbooks/monthly-ckaps-refresh.md`)
followed by local `pdfplumber` parsing.

A source review on 2026-08-12 found the organisational picture correct but the access
route wrong. CKAPS is genuinely the regulator — established February 2003 under the
Medical Practice Division at MOH Putrajaya, with counterpart branches at every state
health department, enforcing the Private Healthcare Facilities and Services Act 1998
(Act 586), with sub-units for Pendaftaran, Pelesenan, and Aduan dan Penguatkuasaan.
But the PDF route fails on three counts:

1. **The published lists are years stale.** The most recent snapshots findable are
   "as of 31.12.2022" and "as of 30 June 2023". A register republished every year or
   two cannot detect a clinic that opened last month — which is GRID's entire purpose.
2. **`hq.moh.gov.my` disallows automated access** (re-confirmed 2026-08-12), so the
   pipeline would depend on indefinite manual downloading.
3. **CKAPS's public systems are transactional, not informational.** MyMedPCs is the
   Borang A application system for practitioners; `ckaps.aduan@moh.gov.my` is a
   complaints channel. Neither is a data feed.

A separate route exists. **MyGeoCKAPS** publishes CKAPS registry data as an ArcGIS
REST service on MyGOS (Malaysia Geospatial Online Services, operated by Pusat
Geospatial Negara), linked from the official malaysia.gov.my private health
facilities page:

- Public app: `https://mygos.mygeoportal.gov.my/mygeockaps_public/`
- REST service: `https://mygos.mygeoportal.gov.my/gisserver/rest/services/KKM/FASILITI_KESIHATAN_SWASTA_PUBLIC/MapServer`

Service metadata shows **layer 5 = Klinik Perubatan Swasta**, with dental
(`Klinik Pergigian Swasta`) isolated in its own layer 4, hospitals in layer 1, and so
on across 16 layers. Query formats JSON/geoJSON/PBF; `MaxRecordCount: 2000` with
`resultOffset`/`resultRecordCount` paging; `esriGeometryPoint` at SRID 4326; national
extent covering Peninsular **and** East Malaysia. PGN ran a data-updating training for
CKAPS officers in January 2024, indicating an active maintenance process.

## Decision

**Replace CKAPS PDF ingestion with an ArcGIS REST adapter querying MyGeoCKAPS layer 5**
as the Phase 1 authoritative spine, subject to the Gate below.

Adopt **ProtectHealth's MADANI / PeKa B40 clinic finder** as the second major source —
a market-entry signal that is GP-only by scheme rule (participation requires
registration as "Klinik Perubatan Swasta"; "Klinik Pakar Perubatan Swasta" is
excluded), paginated and state-filterable, and therefore diffable.

Retain the CKAPS PDFs as a **historical baseline only**, demoted from primary.

## Alternatives considered

| Option | Verdict |
|---|---|
| Keep parsing CKAPS PDFs as the spine | **Rejected** — 2022/2023 vintage cannot support a 30–60 day detection window |
| OpenStreetMap / Overpass as the spine | **Rejected** — not authoritative, worse geometry and coverage than MyGeoCKAPS |
| SSM company data as the spine | **Rejected** — paywalled; scraping prohibited (guardrail 2) |
| Formal data-sharing agreement with CKAPS/PGN *instead of* self-serve querying | **Preferred if granted** — pursued in parallel, not treated as blocking |

## Gate — do not write the adapter until these are answered

Direct verification was impossible from the build environment:
`mygos.mygeoportal.gov.my` returns `ROBOTS_DISALLOWED` to automated fetching, and
guardrail 13 makes that binding on dev tooling and MCP servers, not just production
code. Everything above about the service comes from metadata surfaced in search
results, **not direct inspection**. A human must confirm, in a browser:

1. **Layer 5 field list** — above all, whether a **registration/approval date field
   exists**. This is the single most consequential unknown in the project.
2. **Layer 5 record count**, compared against MOH's 11,067 registered private medical
   clinics (2024). A large shortfall means incomplete GIS coverage.
3. **The `robots.txt` position** and whether low-volume querying of a documented
   public REST endpoint is acceptable.

Also to confirm before the schema is finalised: data freshness/update cadence, whether
phone numbers are present, and whether practitioner names are present (if so, they are
personal data and route to the segregated table).

Tracked as open questions 14–19 in `docs/context/open-questions.md`.

## Consequences

**Positive**

- Geocoding becomes free and authoritative; the Google Geocoding dependency drops out
  of Phase 1 and projected Maps spend falls (`costs.md`).
- PostGIS earns its place immediately — every record arrives with geometry.
- **The GP classification problem largely dissolves.** Dental is a separate layer, so
  `classify/gp_filter.py` shrinks to the specialist-vs-general distinction *within*
  layer 5, plus adjudicating layer 10 (Premis Jagaan Kesihatan Swasta Gabungan).
- A stable unique ID makes snapshot diffing a set difference rather than fuzzy
  matching.
- `pdfplumber` leaves the critical path, and with it the OCR/scanned-page risk and
  open question 3 (the unavailable `pdf-reading` skill).
- Phase 1's first vertical slice gets materially simpler and faster.

**Negative / accepted risks**

- **Access legitimacy is unresolved.** `robots.txt` disallows crawlers; whether a
  documented public REST endpoint queried at low volume sits inside or outside that is
  a judgement call, not a settled position. No adapter ships until it is settled.
- **If layer 5 carries no registration-date field**, "new" must be inferred by diffing
  snapshots over time. GRID's clock then starts at the first pull, and for the first
  few months genuinely-new clinics cannot be distinguished from
  newly-added-to-the-GIS clinics. Queue A would lean harder on `recency_signal`
  corroboration in the interim, and Queue B carries the KPI. This risk is the reason
  for gate item 1.
- Entity resolution is still required — to match across MyGeoCKAPS, ProtectHealth,
  Google Places and the PMCare panel.
- The PMCare panel extract remains the unchanged blocking external dependency; nothing
  in this decision affects it.

## Follow-ups

- `docs/runbooks/` needs a MyGeoCKAPS pull runbook — deferred until the gate clears,
  since a runbook for an unbuilt adapter against an unconfirmed schema is premature.
- Approach CKAPS (`ckaps@moh.gov.my`, 03-8883 1307) and/or Pusat Geospatial Negara for
  written confirmation of acceptable programmatic access, or a formal data-sharing
  arrangement. PMCare is a licensed MCO regulated under the same Act 586 that produced
  this register — a materially stronger position to ask from than an anonymous
  scraper, and a sanctioned feed would close the compliance question permanently.
