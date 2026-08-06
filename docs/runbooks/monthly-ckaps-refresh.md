# Runbook — Monthly CKAPS register refresh (manual, human-performed)

**Never automate any part of the download.** `hq.moh.gov.my` returns
ROBOTS_DISALLOWED; MOH does not sanction automated crawling. GRID's `ckaps` adapter
only validates and parses what a human has placed on disk.

## Cadence

Monthly, first week of the month (CKAPS updates are not on a published schedule —
diffing tolerates gaps).

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
5. Run the ingester (Phase 1 onward): `uv run grid ckaps ingest --date <YYYY-MM-DD>`
   — it records checksums and row counts in the `snapshot` table and fails loudly on
   missing states, zero rows, or PDFs with no text layer (scanned pages must be
   flagged, never silently skipped).
6. Review the ingest report; file anything odd in
   `docs/context/open-questions.md` or as an adapter issue.

## Failure notes

- Missing snapshot folder → the adapter raises an actionable error pointing here.
- A state PDF that is scanned (no text layer) → flag for OCR follow-up; do not
  hand-type data into the warehouse.
