---
title: Open Questions
owner: thiran
last_verified: 2026-08-17
verify_by: 2026-11-15
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

## PR001 provider master — what the codes mean

Questions for the PNM team about the provider master extract (PR001, 33,643 providers,
dated 5 August 2026). Each one is about a field PNM's own systems fill in, so no database
access is needed to answer — the team's working knowledge is the authority. Where the
answer is unknown, GRID records "unknown" rather than a plausible guess (guardrail 10),
and the affected records sit in a review queue instead of the engagement queue.
*(All raised 2026-08-17; evidence in `docs/reconciliation-pr001.md` and ADR 0005.)*

22. **What does the provider "category" letter mean?** Every provider carries a
    single-letter category. Almost all of them share one letter — P covers 33,322 of the
    33,643 — and the rest are spread thinly: G 244, C 28, A 21, F 12, U 11, X 5. Please
    give us the word behind each letter. *What changes:* if any of these letters marks a
    provider that is not a normal panel clinic (a group scheme, a corporate account, a
    test record), GRID must exclude it from the incumbent count, and today it cannot.
23. **What does the "payment method" letter mean?** Three letters are in use: C for
    19,868 providers, M for 11,035, X for 2,740. *What changes:* if one of these marks
    providers who are not actually billing PMCare, our "already on panel" figure is
    overstated and Queue B is being suppressed against providers it should not be.
24. **What does the "ownership" code mean, and why is it filled in for so few?** Four
    codes are used — 0, 1, 2 and 3 — but only 1,300 of the 33,643 providers have one at
    all. Please tell us what the four codes stand for, and whether the field is only
    completed for certain kinds of provider or was simply never rolled out. *What
    changes:* ownership type (sole practitioner vs group vs corporate chain) would be a
    strong prioritisation signal for engagement. If the field is unreliable we will not
    use it, and we should stop presenting it.
25. **What is "LK180"?** There is a field named `id_LK180` holding a small number — 0, 1,
    2 or 3 — for 2,867 providers and nothing for the rest. Nobody here knows what LK180
    refers to. Is it a form number, a scheme, a legacy system, a benefit table? *What
    changes:* if it identifies a scheme or benefit category it becomes part of the
    provider profile; if it is a dead legacy field we drop it and stop carrying it
    forward.
26. **What does provider status "V" mean?** Provider status uses A (active, 29,591), T
    (terminated, 4,032) and S (suspended, 17) — and those three are confirmed by the
    dates that accompany them. Three providers carry a fourth value, V, with neither a
    termination nor a suspension date. Are those three live providers, records in
    progress, or something else? *What changes:* three records is small, but GRID has to
    decide whether they count as part of the incumbent network, and it will not guess.
27. **What are these 14 provider-discipline codes?** The provider-type field uses 21
    codes. We can read seven of them. These 14 we cannot, shown with how many
    providers hold each:
    WP 720, AM 690, MS 637, FS 442, DC 279, TD 22, NA 17, CL 9, IM 6, MT 2, CP 2, PT 2,
    PM 1, FT 1. *What changes:* this is the field that decides whether a provider is a GP
    clinic. GRID is GP/primary-care only (guardrail 7), so any of these 14 that turns out
    to be general practice is currently being left out of the incumbent GP count — and
    any that is a specialist or allied service would wrongly enter it if we guessed
    generously. 2,830 providers sit behind these 14 codes.
28. **Is "HBRN" the MOH facility registration number?** There is a registration-style
    reference recorded for 4,796 of the 33,643 providers under the heading HBRN. Is that
    the facility's registration number with the Ministry of Health under the private
    healthcare facilities legislation, or is it something internal to PMCare? *What
    changes:* this is the single most valuable answer on this list. A confirmed regulator
    registration number would let GRID match a newly registered clinic to a PMCare record
    exactly, instead of matching on name and postcode and accepting the errors that
    brings. It also decides how the field is protected: until confirmed it is treated as
    personal data, because a sole practitioner's registration identifies a person.
29. **Is state code "PJ" Putrajaya?** The state field uses 18 values. Fifteen are the
    states plus Kuala Lumpur and Labuan. Putrajaya — the third federal territory — does
    not appear at all, unless PJ is it. PJ is used by 118 providers. Note that PJ is also
    a very common shorthand for Petaling Jaya, which is a town in Selangor, not a state.
    Which is it? *What changes:* 118 providers are currently assigned to a state we are
    not certain exists in this coding scheme, and state is used both for territory
    planning and as a cross-check on postcodes.
30. **Were the male/female doctor fields meant to be head counts?** Two fields are named
    as though they hold the number of male and the number of female doctors at a clinic,
    but the system stores each of them as a simple yes/no. Was a count intended and
    quietly lost, or has it always been a yes/no? *What changes:* clinic size is a useful
    engagement signal. If these were meant to be counts, the data as stored cannot supply
    them and we should say so rather than report a misleading figure.
31. **What is the difference between the two "AME" flags?** Providers carry two separate
    yes/no flags whose names both refer to AME — one plain, one suffixed MPM. Are they
    the same thing recorded twice, two stages of one scheme, or two unrelated schemes?
    *What changes:* if they are duplicates, one should be retired. If they are different,
    we need to know which one to trust when the two disagree.
32. **What does "LTM" stand for?** There is a yes/no flag named for LTM and nobody here
    can expand the abbreviation. *What changes:* until it is expanded GRID carries the
    flag forward without meaning and never uses it in scoring or reporting. If it turns
    out to be a scheme or accreditation, it may be worth using.

### PR001 provider master — data-quality questions raised by the build (2026-08-17)

33. **Are the notes in the provider records cut short?** Several notes end mid-word, for
    example "…CHANGE TO N" and "…/TAKE ", suggesting the notes field is truncated at
    around 70 characters somewhere between the provider system and this extract.
    *What changes:* the notes are where PNM records that one clinic was re-keyed under a
    new code, and GRID recovered 96 such links from them. If the text is being cut off,
    an unknown number of further links are simply unrecoverable from this extract at any
    level of care, and the fix is a better extract rather than better code. Please confirm
    with whoever produces the extract whether the field is being truncated, and if so
    whether the full text can be supplied.
34. **Can a provider code be shorter than five characters?** Nearly all codes are five to
    twelve characters, but at least one three-character code exists ("GOH").
    *What changes:* the routine that recovers re-keying links ignores short alphabetic
    tokens, because otherwise ordinary words in the notes get mistaken for codes. If short
    codes are genuinely in use, that rule is losing real links and needs revisiting.
35. **Should a clinic's map position be checked against Malaysian territory, and by whom?**
    GRID currently checks a coordinate against a simple rectangle drawn around Malaysia.
    That rectangle unavoidably also covers parts of Indonesia, Singapore, Brunei, southern
    Thailand and open sea, so a coordinate can pass the check while not being in Malaysia
    at all — one repaired record lands in Indonesian Borneo. *What changes:* nothing
    urgent, because coordinates are only ever used to confirm a match and never to make
    one. But if map position is ever to be relied on for territory or state reporting, we
    need an authoritative Malaysian boundary dataset, and someone needs to own sourcing it.

## Closed

- **3. `pdf-reading` public skill unavailable** — closed 2026-08-12. `pdfplumber` left
  the critical path when ADR 0004 replaced PDF parsing with the REST adapter. Reopen
  only if the CKAPS PDF historical-baseline path is ever actually built.
- **13. CKAPS register URL/layout re-verification** — closed 2026-08-12. Verified
  stale: the most recent published snapshots are "as of 31.12.2022" and
  "as of 30 June 2023", which is why ADR 0004 demoted the PDFs to historical baseline.
