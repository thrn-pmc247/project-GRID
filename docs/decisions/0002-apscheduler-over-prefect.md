# 0002 — APScheduler + Typer CLI over Prefect

Date: 2026-08-06 · Status: accepted

## Context

The pipeline needs scheduled runs (monthly CKAPS refresh prompts, weekly enrichment,
Phase 2 adapter cadences) and manual triggers. Prefect offers flows, retries, a UI and
observability — at the cost of a server/agent runtime, more dependencies, and more
operational surface on a single Windows dev machine.

## Decision

Start with **APScheduler for cadence + Typer CLI for manual runs**. Each pipeline
stage is an importable, individually runnable function, so orchestration stays thin.

Revisit (new ADR) when any of these appear: cross-run dependency graphs, distributed
workers, backfill orchestration, or a need for run-history UI beyond structlog + DB
run tables.

## Consequences

- Zero extra infrastructure now; everything runs with `uv run grid …`.
- We forgo Prefect's retries/observability — mitigated by structlog JSON logs, the
  `snapshot` table as a run ledger, and loud adapter health checks.
- Migration path preserved: stage functions are orchestration-agnostic.
