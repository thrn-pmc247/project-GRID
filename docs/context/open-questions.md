---
title: Open Questions
owner: thiran
last_verified: 2026-08-12
verify_by: 2026-11-10
covers_paths: []
status: current
---

# Open questions

Unresolved decisions for the human. Do not guess these — ask. Remove items when
answered and record the answer (ADR or the relevant context file).

## Blocking for Phase 1

1. **PMCare panel extract** — current panel size and the format of the extract
   (CSV/XLSX/API? which fields?). Sets the exact Queue B size and the suppression
   schema. Unaffected by the ADR 0004 source change — still blocking.
   *(Raised 2026-08-06.)*
2. **Docker Desktop** is not installed on this machine — install (or point at another
   Postgres 16 + PostGIS instance) so migrations can run. PostGIS is now load-bearing
   from the first migration, since MyGeoCKAPS supplies native geometry.
   *(Found 2026-08-06.)*

### MyGeoCKAPS verification — blocks the Phase 1 adapter (ADR 0004)

Answer 14–16 in a **browser** before any `sources/mygeockaps.py` is written. Automated
fetching of `mygos.mygeoportal.gov.my` is prohibited until 16 is settled (guardrail 13).

14. **Does layer 5 expose a registration/approval date field?** Retrieve the full field
    list from
    `https://mygos.mygeoportal.gov.my/gisserver/rest/services/KKM/FASILITI_KESIHATAN_SWASTA_PUBLIC/MapServer/5?f=pjson`.
    **This is the single most consequential unknown in the project.** Without such a
    field, "new" is only inferable by diffing forward from the first snapshot: GRID's
    clock starts at the first pull, and for the first few months genuinely-new clinics
    cannot be distinguished from newly-added-to-the-GIS clinics. Queue A would then
    rest entirely on `recency_signal` corroboration. *(Raised 2026-08-12.)*
15. **Layer 5 record count** — compare against MOH's 11,067 registered private medical
    clinics (2024). A large shortfall means incomplete GIS coverage and the spine may
    need rethinking again. *(Raised 2026-08-12.)*
16. **Access legitimacy.** Read `https://mygos.mygeoportal.gov.my/robots.txt` and
    establish whether low-volume querying of a documented public REST endpoint is
    acceptable. Preferred resolution: written confirmation or a formal data-sharing
    arrangement from CKAPS (`ckaps@moh.gov.my`, 03-8883 1307) and/or Pusat Geospatial
    Negara. PMCare is a licensed MCO regulated under the same Act 586 that produced the
    register — a stronger basis to ask from than an anonymous scraper.
    *(Raised 2026-08-12.)*

### MyGeoCKAPS — needed before the schema is finalised

17. **Data freshness and update cadence.** Is there an update-date field or service
    metadata showing last edit? PGN ran a CKAPS data-updating training in January 2024,
    implying active maintenance, but cadence is unknown. *(Raised 2026-08-12.)*
18. **Are phone numbers included?** The register PDFs did not carry them; the GIS layer
    may. Determines how much Google Places enrichment Phase 1 actually needs.
    *(Raised 2026-08-12.)*
19. **Do practitioner names appear in layer 5?** If so they are personal data and route
    to the segregated `practitioner` table, never `clinic`. *(Raised 2026-08-12.)*

## Needs a business/compliance answer

4. Google Maps Platform: is billing already provisioned, and what is the approved
   monthly ceiling in RM? (`costs.md` — requires business owner sign-off.) **Scope
   reduced** — MyGeoCKAPS supplies geocoding, so Places is contact enrichment only.
5. Does PMCare have an appointed DPO and an existing PDPA processing register GRID
   must be added to? (Mandatory since 1 June 2025.)
6. Which competitor panels is PMCare comfortable diffing, given commercial
   sensitivity?
7. Must the PNM team's existing CRM be the system of record, with GRID feeding it
   rather than owning the `engagement` table?
20. **ProtectHealth ToS** — is scraping the MADANI / PeKa B40 clinic finder acceptable,
    and what is the current district coverage of the MADANI pilot (reported as ~10
    districts, second-hand)? Determines whether source 2 is national or partial.
    *(Raised 2026-08-12.)*

## Needs verification (don't state as fact until checked)

8. MOH gross-new-registration vs closure split — research found only an older
   2014–2017 breakdown; confirm current figures with MOH publications.
9. Do Sabah and Sarawak need separate handling for state health department
   processes? MyGeoCKAPS layer 5 extents cover East Malaysia, but per-state data
   completeness is unconfirmed.
10. **CMA s.233A commencement status at build time** — not in force as of the
    2026-08-06 brief; re-check before any outreach send capability is even designed.
11. Exact PDPA breach-notification deadlines (Commissioner + data subjects) per the
    current JPDP guideline — the runbook cites the obligation but the deadlines
    must be verified against the live guideline before first reliance.
12. Authoritative postcode→state/district dataset (Pos Malaysia-derived) for
    `normalise/addresses.py`. **Downgraded from blocking** — MyGeoCKAPS supplies
    authoritative geometry and `NEGERI`, so this becomes a validation nicety for the
    spine. Still required for sources that arrive without geometry (job boards,
    directories, ProtectHealth). Do not code the mapping table from folklore ranges.
21. **MADANI panel growth figures** (750+ clinics August 2023 → a reported 1,205 in
    2026) come from secondary Malaysian news sources, not ProtectHealth primary
    material. Do not quote as fact (guardrail 10). *(Raised 2026-08-12.)*

## Closed

- **3. `pdf-reading` public skill unavailable** — closed 2026-08-12. `pdfplumber` left
  the critical path when ADR 0004 replaced PDF parsing with the REST adapter. Reopen
  only if the CKAPS PDF historical-baseline path is ever actually built.
- **13. CKAPS register URL/layout re-verification** — closed 2026-08-12. Verified
  stale: the most recent published snapshots are "as of 31.12.2022" and
  "as of 30 June 2023", which is why ADR 0004 demoted the PDFs to historical baseline.
