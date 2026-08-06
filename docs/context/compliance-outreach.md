---
title: Compliance — Outreach
owner: thiran
last_verified: 2026-08-06
verify_by: 2026-11-04
covers_paths:
  - src/grid/api/**
status: current
---

# Outreach compliance

GRID's job is discovery and queueing. Outreach execution is human, phone-first, to the
clinic's **published business line**.

## Statutory position (verify at build time — do not assume)

- The Communications and Multimedia (Amendment) Act 2025 commenced 11 February 2025.
- **s.233A (unsolicited commercial electronic messages) is not yet in force** — it
  awaits subsidiary regulations. Treat commencement as imminent; re-check status
  before enabling any send capability (`open-questions.md`).
- Healthcare-adjacent advertising rules (MMC guidelines, Medicines (Advertisement &
  Sale) Act 1956) are unlikely to apply to B2B panel-recruitment contact, but any
  outward copy is a draft requiring human review regardless.

## Design rules (encoded in schema and config)

1. **No mass automated WhatsApp/email blasting. Ever.**
2. Consent-first, phone-first: target the published business line; every contact
   attempt is logged in `engagement.contact_attempts`.
3. Opt-out is recorded (`engagement.opt_out_at`) and **permanently honoured** —
   Phase 3 acceptance requires provable suppression.
4. Any actual send capability sits behind `GRID_OUTREACH_SEND_ENABLED`
   (pydantic-settings, defaults `false`) and **requires PMCare compliance sign-off
   before it is ever set true**. The flag exists from day one so the gate is
   structural, not aspirational.
5. Outreach copy never positions PMCare as insurer or clinician, never contains
   clinical claims, and always carries a human-review marker.
