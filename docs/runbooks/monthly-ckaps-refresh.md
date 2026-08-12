# Runbook — CKAPS register PDF pull (historical baseline only)

> **DEMOTED 2026-08-12 (ADR 0004).** This is **no longer the primary ingestion path**
> and is not part of the monthly cadence. The published register PDFs are years stale —
> the most recent findable snapshots are "as of 31.12.2022" and "as of 30 June 2023" —
> so they cannot detect a clinic that opened last month, which is GRID's whole purpose.
> The Phase 1 spine is now the MyGeoCKAPS ArcGIS REST service (layer 5); see
> `docs/context/data-sources.md`.
>
> Use this procedure only to obtain a **historical baseline** for back-fill or
> cross-checking, on an ad hoc basis.

**Never automate any part of the download.** `hq.moh.gov.my` returns
ROBOTS_DISALLOWED (re-confirmed 2026-08-12); MOH does not sanction automated crawling.
Any `ckaps_pdf` adapter only validates and parses what a human has placed on disk.

## Cadence

**Ad hoc only.** There is no monthly CKAPS PDF cadence any more — the source does not
republish often enough for one to be meaningful.

## Procedure

1. In a normal browser, open the MOH CKAPS private clinic register page:
   `https://hq.moh.gov.my/medicalprac/senarai-klinik-perubatan-swasta/`
   (URL current as of 2026-08-06 — if moved, navigate from hq.moh.gov.my and update
   this runbook + `docs/context/data-sources.md`).
2. Download the register PDF(s) for **all** states and federal territories,
   including Sabah and Sarawak.
3. Create the snapshot folder using today's date:
   `data/raw/ckaps/<YYYY-MM-DD>/`
4. Save each PDF into that folder named by state slug, e.g. `johor.pdf`,
   `wp-kuala-lumpur.pdf`, `sabah.pdf`. Do not rename after ingestion.
5. Run the ingester (only if the `ckaps_pdf` baseline adapter is ever built):
   `uv run grid ckaps-pdf ingest --date <YYYY-MM-DD>`
   — it records checksums and row counts in the `snapshot` table and fails loudly on
   missing states, zero rows, or PDFs with no text layer (scanned pages must be
   flagged, never silently skipped).
6. Review the ingest report; file anything odd in
   `docs/context/open-questions.md` or as an adapter issue.

## Failure notes

- Missing snapshot folder → the adapter raises an actionable error pointing here.
- A state PDF that is scanned (no text layer) → flag for OCR follow-up; do not
  hand-type data into the warehouse.
