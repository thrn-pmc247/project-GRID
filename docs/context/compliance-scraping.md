---
title: Compliance — Scraping & Source Access
owner: thiran
last_verified: 2026-08-06
verify_by: 2026-11-04
covers_paths:
  - src/grid/sources/**
status: current
---

# Source access compliance

Every adapter declares its position here **and** in its `SourceMeta.legal_basis`
(enforced by `scripts/check_context.py`). `/new-adapter` scaffolds both. MCP tools and
dev-time browsing obey the same rules as production code — an MCP server is not an
exemption.

## Absolute prohibitions

| Target | Rule | Basis |
|---|---|---|
| `hq.moh.gov.my` (CKAPS) | **Never crawled, by anything.** Register PDFs are manually downloaded by a human per `docs/runbooks/monthly-ckaps-refresh.md`, then parsed locally. `.claude/settings.json` denies WebFetch to the domain as a belt-and-braces guard. | Site returns ROBOTS_DISALLOWED; MOH does not sanction automated crawling. |
| SSM (MyData / e-Info / EzBiz) | **Never scraped.** Paid per-document access or a licensed reseller only, if ever needed. | SSM ToS prohibit automated scraping and bulk harvesting. |

## Google Places

- Persist **`place_id` only, indefinitely** (permitted). All other Places content is
  refreshed on read, never cached — Google Maps Platform ToS restriction.
- Enforced in code: `enrich/geocode.py` (Phase 1) must have no persistence path for
  non-`place_id` Places fields, and `clinic` carries only `google_place_id`.

## General adapter rules

1. Check `robots.txt` and per-site ToS **before** writing the adapter; record the
   position in `data-sources.md` and in `SourceMeta.legal_basis`.
2. Rate-limit; descriptive User-Agent identifying PMCare and a contact address;
   exponential backoff on 429/403; stop entirely on explicit prohibition.
3. Prefer official APIs and published data files over HTML scraping.
4. Job boards and directories commonly have anti-scraping terms — each target gets an
   explicit verdict here before its adapter ships. None assessed yet (Phase 2).

## Per-source register

| Source | robots/ToS position | Verdict | Checked |
|---|---|---|---|
| MOH CKAPS | ROBOTS_DISALLOWED | manual download only | 2026-08-06 (per project brief; re-verify at Phase 1 build) |
| SSM | ToS prohibit scraping | never scrape | 2026-08-06 (per project brief) |
| Google Places | API ToS: no caching beyond place_id | API with storage guardrail | 2026-08-06 |
| SOCSO panel list | not yet assessed | TBD before Phase 2 build | — |
| OSM Overpass | ODbL + Overpass usage policy | API, rate-limited | not yet assessed in detail |
| GetDoc / DoctorOnCall / other directories | not yet assessed | TBD per directory | — |
| Job boards | not yet assessed | TBD per board | — |
| News/RSS, social platforms | not yet assessed | TBD | — |
