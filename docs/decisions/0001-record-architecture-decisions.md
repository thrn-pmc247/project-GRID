# 0001 — Record architecture decisions

Date: 2026-08-06 · Status: accepted

## Context

GRID is agent-assisted and compliance-heavy. Decisions lose their rationale fast when
the reasoning lives only in chat transcripts or commit messages.

## Decision

Record every decision that had genuine alternatives as an ADR in `docs/decisions/`,
numbered `NNNN-slug.md`, contiguous from 0001 (enforced as a warning by
`scripts/check_context.py`). Scaffold with `/adr <title>`. Format: Context, Decision,
Consequences — short is fine; missing is not.

## Consequences

Revisiting a choice starts from its ADR, not from archaeology. The Definition of Done
in `CLAUDE.md` requires an ADR for any decision with alternatives.
