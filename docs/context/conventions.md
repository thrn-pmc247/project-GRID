---
title: Conventions
owner: thiran
last_verified: 2026-08-18
verify_by: 2026-11-16
covers_paths:
  - src/**
  - tests/**
  - scripts/**
status: current
---

# Conventions

## Code

- `ruff` for lint + format (line length 100); `mypy --strict` on `src/`; type hints
  everywhere; Google-style docstrings.
- `pathlib` for all paths. No bash scripts — hooks and tooling are Python so they run
  in PowerShell.
- Errors fail loudly and specifically. **A source returning zero rows is a failure**,
  not an empty success. Health checks alert; they never silently pass on layout drift.
- Logging via `structlog` (JSON in prod). **Never log PII or full raw payloads** —
  counts and internal IDs only.
- British/Malaysian English in all prose, docstrings and user-facing strings
  (normalise, licence, centre). Currency RM.

## Commits

Conventional Commits: `feat(sources): add SOCSO panel adapter`,
`fix(normalise): handle P. Pinang variant`, `docs(context): …`, `chore: …`.
Reference the ADR when a decision is embedded (`refs ADR 0002`).

## Tests

- `pytest`; fixtures are **synthetic only** — never real clinic data or PII.
- Every adapter: a parse test against a redacted/synthetic sample.
- Every normalisation rule: table-driven cases.
- Entity resolution: labelled pair set with tracked precision/recall.
- `tests/test_context_hygiene.py` runs the context gate, so plain `pytest` catches
  documentation drift too.

## Context maintenance

`CLAUDE.md` is a **router, not a manual** — ≤150 lines / ≤1,200 words, enforced by
`scripts/check_context.py` (pre-commit + CI + pytest + Claude Code session hooks).

- Every `docs/context/*.md` carries front matter: `title`, `owner`, `last_verified`,
  `verify_by` (≤90 days out), `covers_paths`, optional `external_sources`, `status`.
- **Definition of Done for every task** includes: update every affected context file,
  bump its `last_verified`, and get `check_context.py` to exit 0. Decisions with
  alternatives become ADRs; new uncertainty goes to `open-questions.md`.
- Drift detection: commits under a file's `covers_paths` newer than its
  `last_verified` fail the gate.

### Split protocol

When a context file exceeds 300 lines or covers more than one concern:

1. Create the new scoped file with full front matter.
2. **Move — never summarise away — the content.** A guardrail lost to a line budget
   is a compliance incident waiting to happen.
3. Leave a one-line pointer in the original if cross-reference is useful.
4. Add rows to `CLAUDE.md`'s context map and regenerate `INDEX.md`
   (`check_context.py --fix`).
5. Run `check_context.py`; record the split in the commit message.

Prefer many small, sharply scoped files. `data-sources.md` will outgrow first — the
checker already tolerates it becoming a `data-sources/` directory with one file per
source.
