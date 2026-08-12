# Runbook — Adapter failure triage

Sources change layout without warning. A failing `health_check()` or a zero-row parse
is an **alert**, never an empty success (conventions.md).

## Symptoms → first moves

| Symptom | First move |
|---|---|
| `health_check` fails (shape changed) | Diff the live page/PDF structure against the adapter's recorded expectations; inspect with the Playwright MCP server (dev only) |
| Zero rows parsed | Check the snapshot exists; check for a silent format change; never ship a "fixed" parser that returns fewer fields without noting it. PDF baseline path only: confirm a text layer (`pdfplumber`) |
| HTTP 403/429 | Back off. Check robots.txt/ToS again — access terms may have changed. If access is now prohibited, **stop the adapter** and update `docs/context/compliance-scraping.md` + `data-sources.md` before anything else |
| MyGeoCKAPS returns fewer records than the last snapshot | Treat as a **failure, not a shrinking market**. Re-run paging (`resultOffset`/`resultRecordCount`) before concluding anything — a truncated page loop looks exactly like clinic closures and would silently corrupt the differ |
| MyGeoCKAPS layer IDs or field names changed | Stop. Re-verify the layer map in `data-sources.md` and the field list (open q. 14) before parsing — layer 5 must still be Klinik Perubatan Swasta |
| CKAPS PDF snapshot missing | Not a code bug, and not urgent — the PDFs are a historical baseline only (ADR 0004). See `docs/runbooks/monthly-ckaps-refresh.md` |

## Rules

1. Fix the adapter **and** its fixtures — every layout change becomes a synthetic
   test case.
2. If the source's ToS/robots position changed, the compliance register update is
   part of the fix, not a follow-up.
3. If a source is dead or newly prohibited, mark its verdict accordingly in
   `data-sources.md`, note the queue-volume impact in `roadmap.md`, and raise it —
   Queue B depth is the KPI safety net.
4. Definition of Done applies: affected context docs updated, `check_context.py`
   green.
