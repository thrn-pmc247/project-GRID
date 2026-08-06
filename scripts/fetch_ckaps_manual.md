# fetch_ckaps_manual — a human procedure, deliberately not a script

There is intentionally **no automation** here: `hq.moh.gov.my` returns
ROBOTS_DISALLOWED and is never crawled by GRID, its MCP servers, or any dev tooling
(CLAUDE.md guardrail 1).

The full procedure lives in `docs/runbooks/monthly-ckaps-refresh.md`. Short form:

1. Browser → `https://hq.moh.gov.my/medicalprac/senarai-klinik-perubatan-swasta/`
2. Download every state/FT register PDF (all 16, incl. Sabah & Sarawak).
3. Save to `data/raw/ckaps/<YYYY-MM-DD>/<state-slug>.pdf`.
4. `uv run grid ckaps ingest --date <YYYY-MM-DD>` (available from Phase 1).
