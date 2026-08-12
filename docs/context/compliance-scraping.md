---
title: Compliance — Scraping & Source Access
owner: thiran
last_verified: 2026-08-12
verify_by: 2026-11-10
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
| `mygos.mygeoportal.gov.my` (MyGeoCKAPS) | **No automated fetching of any kind until open question 16 is answered** — this binds WebFetch, MCP servers and dev-time browsing, not just adapter code. Human browser inspection is fine. | Host returned ROBOTS_DISALLOWED to automated access on 2026-08-12. |

## MyGeoCKAPS — unresolved, and deliberately so

ADR 0004 makes the MyGeoCKAPS ArcGIS REST service the intended Phase 1 spine. Its
access position is **not settled**:

- `robots.txt` disallows crawlers. What that means for a *documented public REST
  endpoint queried at low volume* is a judgement call, not a decided position.
- MyGOS is described as an inter-agency geospatial sharing platform, which suggests a
  **formal data-sharing route may exist and would be cleaner than self-serve querying**.
- Everything currently known about the service comes from metadata surfaced in search
  results. It has never been directly inspected from this environment, by design.

**Therefore:** no `SourceMeta.legal_basis` can be written honestly for this adapter
yet, and check 10 in `check_context.py` would reject a placeholder. That is the gate
working as intended — not an obstacle to route around.

**Preferred resolution:** approach CKAPS (`ckaps@moh.gov.my`, 03-8883 1307) and/or
Pusat Geospatial Negara for written confirmation of acceptable programmatic access, or
a formal data-sharing arrangement. PMCare is a licensed MCO regulated under the same
Act 586 that produced this register — a materially stronger basis to ask from than an
anonymous scraper, and a sanctioned feed closes the question permanently.

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
| **MyGeoCKAPS (mygos.mygeoportal.gov.my)** | **ROBOTS_DISALLOWED to automated access** | **BLOCKED pending open q. 16** — no fetching by any tooling; seek written permission or a data-sharing route | 2026-08-12 |
| MOH CKAPS (hq.moh.gov.my) | ROBOTS_DISALLOWED | manual download only; demoted to historical baseline (ADR 0004) | 2026-08-12 (re-confirmed) |
| SSM | ToS prohibit scraping | never scrape | 2026-08-06 (per project brief) |
| Google Places | API ToS: no caching beyond place_id | API with storage guardrail | 2026-08-06 |
| **ProtectHealth clinic finder** | not yet assessed | **TBD before build** — check ToS on the finder before any adapter | 2026-08-12 (URL structure only) |
| **PERKESO / SOCSO panel search** | Interactive portal behind an **F5 WAF that rejected automated requests**; treat rejection as a signal, not an obstacle to defeat | TBD — likely manual or permissioned; **listings carry doctors' names → personal data** | 2026-08-12 |
| KKMNOW / data.gov.my | Open data, CC BY 4.0, documented API | **permitted** — use `api.data.gov.my` | 2026-08-12 |
| OSM Overpass | ODbL + Overpass usage policy | API, rate-limited; downgraded to cross-check | not yet assessed in detail |
| GetDoc / DoctorOnCall / other directories | not yet assessed | TBD per directory | — |
| Job boards | not yet assessed | TBD per board | — |
| News/RSS, social platforms | not yet assessed | TBD | — |

**On WAF rejections:** a source that actively blocks automated requests (PERKESO's F5)
has expressed a position. Engineering around it is out of scope — pursue a manual or
permissioned route instead.
