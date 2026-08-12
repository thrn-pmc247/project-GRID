---
name: ckaps-register-parser
description: "HISTORICAL BASELINE ONLY (superseded by ADR 0004 — the Phase 1 spine is now the MyGeoCKAPS ArcGIS REST service, not these PDFs). Working knowledge for MOH CKAPS private-clinic register PDFs — snapshot layout, pdfplumber parsing, the scope-column taxonomy (Klinik Umum), per-state quirks and snapshot diffing. Use ONLY when parsing the stale 2022/2023 register PDFs for back-fill or cross-checking, not for new-clinic detection."
---

# CKAPS register parsing

> **Superseded 2026-08-12 (ADR 0004).** The published register PDFs are years stale
> (most recent: "as of 31.12.2022" and "as of 30 June 2023") and cannot detect a
> clinic that opened last month. The Phase 1 spine is the MyGeoCKAPS ArcGIS REST
> service, layer 5 — see `docs/context/data-sources.md`. This skill applies only to
> the historical-baseline path.

## Non-negotiable access rule

`hq.moh.gov.my` is **never crawled** (ROBOTS_DISALLOWED). Snapshots are downloaded by
a human per `docs/runbooks/monthly-ckaps-refresh.md` into
`data/raw/ckaps/<YYYY-MM-DD>/<state-slug>.pdf`. The adapter's `fetch()` only
validates that the snapshot exists — if missing, raise an actionable error pointing
at the runbook. Never "helpfully" download.

## What the register gives you

Clinic name, full address, postcode, state, **scope** (`Klinik Umum` vs specialist
descriptions), and sometimes an Act 586 registration number. The **scope column is
the single best GP filter anywhere** — treat it as ground truth that other sources'
classifiers are calibrated against. Person-in-charge names, if present, are personal
data: strip at parse time (see `pdpa-review` skill), do not warehouse in raw JSONB.

## Parsing strategy

1. Verify a text layer exists before parsing (pdfplumber page `.chars` non-empty /
   `pypdf` font inspection). A scanned state list must be **flagged loudly** — OCR
   is a recorded follow-up, never a silent zero-row result.
2. `pdfplumber.extract_tables()` first; fall back to `extract_text()` with
   line-pattern reconstruction where the table detection fails.
3. Zero rows from any state = **failure**, not an empty success.
4. Record per-state row counts and a field-completeness report on every ingest;
   compare against the previous snapshot's counts (big drops = layout change).

## Snapshot discipline

- Snapshots are immutable; checksums (sha256) and row counts go to the `snapshot`
  table. Never edit a landed PDF; a corrected download is a new snapshot folder.
- Diffing: new registrations = records in snapshot N absent from all prior
  snapshots (match on registration number when present, else resolved entity).
  **Genuinely new (Queue A) additionally requires ≥1 recency signal** — otherwise
  the record is newly-listed-but-pre-existing → Queue B
  (`docs/context/entity-resolution.md`).

## Honest unknowns (update this skill at first real snapshot)

The exact current PDF layout, column order, per-state formatting quirks and the full
scope-value taxonomy have **not been verified against a live snapshot yet** — the
first Phase 1 task is to inspect a real download and replace this section with
measured facts. Do not invent layout details; anything asserted here beyond the
project brief must come from an actual snapshot.
