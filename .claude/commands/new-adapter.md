---
description: Scaffold a source adapter with tests, data-sources row and compliance entry in one go
argument-hint: [source-key, e.g. socso_panel]
---

Scaffold the source adapter: $ARGUMENTS

Docs are part of the adapter, not a follow-up — checks 9 and 10 of
`scripts/check_context.py` make an undocumented adapter unshippable.

1. **Compliance first.** Check the source's robots.txt and ToS position. Record the
   verdict in the per-source register in `docs/context/compliance-scraping.md`
   (bump its front matter). If access is prohibited: STOP, record that, and propose
   a compliant alternative (official API, published files, manual download,
   licensed purchase). Never scaffold anything that crawls `hq.moh.gov.my` or
   scrapes SSM.
2. Read `docs/context/data-sources.md` and `docs/context/architecture.md` (adapter
   contract).
3. Create `src/grid/sources/$ARGUMENTS.py` implementing `SourceAdapter` from
   `sources/base.py`, with a complete `SourceMeta` — `legal_basis` must be a real,
   specific justification, not boilerplate.
4. Create `tests/unit/test_source_$ARGUMENTS.py` with a parse test against a
   **synthetic** fixture in `tests/fixtures/` (never real data).
5. Add the adapter's row to `docs/context/data-sources.md`; bump `last_verified`.
6. Run `uv run python scripts/check_context.py` and `uv run pytest` — both must
   pass before the adapter is considered created.
