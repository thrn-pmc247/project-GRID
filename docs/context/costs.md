---
title: Costs
owner: thiran
last_verified: 2026-08-06
verify_by: 2026-11-04
covers_paths:
  - src/grid/enrich/**
status: current
---

# Costs

> **Every figure on this page requires business owner sign-off before any spend is
> committed. Nothing here is an approved budget.** Commercial/pricing questions go to
> the business owner (CLAUDE.md guardrail 12).

## Cost drivers

| Item | Driver | Note |
|---|---|---|
| Google Maps Platform (Places Details, Text Search, Geocoding) | ~11k registered private clinics for initial enrichment + weekly refresh of active-queue records + `place_id` re-resolution on read (no caching of Places content) | **Unpriced here deliberately.** Per-SKU prices must be taken from the live Google pricing page at provisioning time and converted to RM; monthly ceiling in RM needs business owner sign-off before the API key is provisioned (`open-questions.md`). |
| SSM documents | only if a concrete need arises; per-document purchase or licensed reseller | none identified yet — do not budget until a use case exists |
| Job-board API access | Phase 2, if a board offers licensed API access as the compliant route | assess per board during Phase 2 |
| Infra | local dev is free (Docker Postgres); hosting decision not yet made | open question for Phase 3 |

## Call-volume arithmetic (for the sign-off conversation)

Derivable from the project brief, not a price: initial backfill ≈ one Places lookup
per registered clinic (~11k); steady state ≈ (new + changed + active-queue refresh)
well under 2k lookups/month. Multiply by live SKU prices when requesting the ceiling.
