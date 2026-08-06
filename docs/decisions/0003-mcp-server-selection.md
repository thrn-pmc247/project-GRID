# 0003 — MCP server selection and exclusions

Date: 2026-08-06 · Status: accepted

## Context

Principle: native tools first — every MCP server is context overhead and a
supply-chain consideration. Package names/status were verified against live
registries on 2026-08-06 (not from memory): the original reference
`@modelcontextprotocol/server-postgres` is deprecated (repo archived 29 May 2025,
npm package flagged "no longer supported").

## Decision — configured in `.mcp.json` (project scope)

| Server | Package / command | Scope & rationale |
|---|---|---|
| `playwright` | `npx @playwright/mcp@latest` (Microsoft, active) | Dev-time inspection of JS-rendered directories only. Production scraping uses the pinned `playwright` library in code. |
| `fetch` | `uvx mcp-server-fetch` (Anthropic-maintained reference server, active) | Retrieving public pages/docs during development. Same robots/ToS guardrails as production — not an exemption. |
| `postgres` | `uvx postgres-mcp --access-mode=restricted` (CrystalDBA Postgres MCP Pro; maintained, parser-enforced read-only) | Inspect the dev warehouse, sanity-check entity-resolution output, validate migrations. Restricted mode + (defence-in-depth) connect as a SELECT-only role once the DB exists. Chosen over `@bytebase/dbhub` (fresher releases but read-only requires a TOML sidecar) and over the deprecated reference server. |

## Explicitly not configured

- **Anything automating `hq.moh.gov.my` or SSM** — the §2 guardrails apply to MCP
  identically; `.claude/settings.json` additionally denies WebFetch to those domains.
- **Filesystem server** — not needed: CKAPS PDFs land inside the repo at
  `data/raw/ckaps/`, so no outside-repo access exists to scope. Reconsider only if
  the download landing zone moves outside the repo, and then scope to that one
  directory.
- **Google Maps MCP** — deferred to Phase 1 enrichment work; the archived reference
  server is not an option, and production Places calls go through `src/grid/enrich/`
  so quota and the place_id-only rule stay controlled.
- **GitHub / Git / Slack / sequential-thinking** — Tier 2 in the brief; add when the
  relevant phase starts and native tooling proves insufficient.

## Consequences

Three narrow, verified servers; scopes recorded in `docs/context/environment.md`.
`postgres-mcp`'s slow release cadence is accepted for now — re-evaluate if it stops
receiving maintenance. Node.js is required for `npx`-based servers (see
`open-questions.md` if absent on a machine).
