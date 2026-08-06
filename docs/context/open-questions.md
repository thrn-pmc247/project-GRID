---
title: Open Questions
owner: thiran
last_verified: 2026-08-06
verify_by: 2026-11-04
covers_paths: []
status: current
---

# Open questions

Unresolved decisions for the human. Do not guess these — ask. Remove items when
answered and record the answer (ADR or the relevant context file).

## Blocking for Phase 1

1. **PMCare panel extract** — current panel size and the format of the extract
   (CSV/XLSX/API? which fields?). Sets the exact Queue B size and the suppression
   schema. *(Raised 2026-08-06.)*
2. **Docker Desktop** is not installed on this machine — install (or point at another
   Postgres 16 + PostGIS instance) so migrations can run. *(Found 2026-08-06.)*
3. **`pdf-reading` public skill** — the brief requires reading
   `/mnt/skills/public/pdf-reading/SKILL.md` before writing `ckaps.py`, but no such
   skill is available in this environment (path is Linux-style; skill not in the
   session's skill list). Confirm where it lives for this install, or approve
   proceeding on `pdfplumber`/`pypdf` documentation alone. *(Found 2026-08-06.)*

## Needs a business/compliance answer

4. Google Maps Platform: is billing already provisioned, and what is the approved
   monthly ceiling in RM? (`costs.md` — requires business owner sign-off.)
5. Does PMCare have an appointed DPO and an existing PDPA processing register GRID
   must be added to? (Mandatory since 1 June 2025.)
6. Which competitor panels is PMCare comfortable diffing, given commercial
   sensitivity?
7. Must the PNM team's existing CRM be the system of record, with GRID feeding it
   rather than owning the `engagement` table?

## Needs verification (don't state as fact until checked)

8. MOH gross-new-registration vs closure split — research found only an older
   2014–2017 breakdown; confirm current figures with MOH publications.
9. Do Sabah and Sarawak need separate handling for state health department
   processes?
10. **CMA s.233A commencement status at build time** — not in force as of the
    2026-08-06 brief; re-check before any outreach send capability is even designed.
11. Exact PDPA breach-notification deadlines (Commissioner + data subjects) per the
    current JPDP guideline — the runbook cites the obligation but the deadlines
    must be verified against the live guideline before first reliance.
12. Authoritative postcode→state/district dataset (Pos Malaysia-derived) for
    `normalise/addresses.py` — do not code the mapping table from folklore ranges.
13. CKAPS register URL/layout re-verification at Phase 1 start (external source can
    change without notice): https://hq.moh.gov.my/medicalprac/senarai-klinik-perubatan-swasta/
    — download manually only.
