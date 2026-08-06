"""Source adapters — one module per source, uniform contract.

Contract (SourceAdapter/SourceMeta): docs/context/architecture.md.
Access rules and verdicts: docs/context/data-sources.md and
docs/context/compliance-scraping.md. Every adapter must declare SourceMeta with a
non-empty legal_basis — enforced by scripts/check_context.py (checks 9 and 10).
Scaffold new adapters with the /new-adapter slash command.

Modules land from Phase 1 (base.py, ckaps.py first) per docs/context/roadmap.md.
"""
