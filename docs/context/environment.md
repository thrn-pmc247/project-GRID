---
title: Environment
owner: thiran
last_verified: 2026-08-06
verify_by: 2026-11-04
covers_paths:
  - pyproject.toml
  - compose.yaml
  - .env.example
  - .pre-commit-config.yaml
  - .claude/**
  - .mcp.json
  - .github/**
status: current
---

# Environment

## Machine

Windows 11 Pro, repo at `C:\Users\thiranbarath\Documents\GitHub\project-grid`.
PowerShell is the primary shell; every hook/script is Python (never bash) so it runs
identically cross-platform. `.gitattributes` pins `* text=auto eol=lf`. Paths in code
always via `pathlib`, never hardcoded `/` or `\`.

## Python

- **Python 3.12 via `uv`** (`.python-version` pinned). `uv sync --all-groups` installs
  everything; `uv run <cmd>` executes in the venv. Fallback if uv is unavailable:
  `py -3.12 -m venv .venv` (note: the `py` launcher is currently NOT installed on this
  machine — uv manages the interpreter).
- PDF parsing is **pure-Python first** (`pdfplumber`, `pypdf`) so the pipeline runs
  without system binaries. Poppler (`pdfinfo`/`pdftotext`/`pdftoppm`) is optional; if
  ever needed on Windows, document the install path here before depending on it.
- Playwright browsers are NOT installed yet — `uv run playwright install chromium`
  when Phase 2 scraping work starts.

## Database

Postgres 16 + PostGIS via Docker Desktop: `docker compose up -d db` (`compose.yaml`),
bound to `127.0.0.1:5432`. Migrations via Alembic (`alembic.ini`,
`src/grid/db/migrations/`). **Status 2026-08-06: Docker Desktop is not installed on
this machine** — install it, then compose up and run migrations
(`open-questions.md`).

## Secrets

`.env` only (gitignored), loaded by `pydantic-settings` (`src/grid/config.py`,
`GRID_` prefix). `.env.example` documents every variable — enforced by check 12 of
`scripts/check_context.py`. Never put credentials in code, compose defaults are
dev-only.

## Quality gates

- `uv run pre-commit install` once per clone. Hooks: large-file/private-key guards,
  ruff lint+format, mypy (src), and the context gate (`scripts/check_context.py`).
- CI (`.github/workflows/ci.yml`) runs the same set plus pytest, with full git
  history (`fetch-depth: 0`) so drift detection works.
- Claude Code hooks (`.claude/settings.json`): `SessionStart` runs the context check
  with `--report`; `Stop` runs it plainly. Both events are non-blocking by design
  (verified against Claude Code docs 2026-08-06) — they surface drift, they cannot
  deadlock a session.

## MCP servers (project scope, `.mcp.json`)

Principle: native tools first; every server is context overhead and a supply-chain
consideration. Decisions and the do-not-configure list: ADR 0003.

| Server | Scope | Why |
|---|---|---|
| `playwright` (`@playwright/mcp`) | dev-time page inspection only | JS-rendered directories; production scraping uses the pinned `playwright` library in code |
| `fetch` (`mcp-server-fetch` via uvx) | public pages/docs during development | same robots/ToS guardrails as production — not an exemption |
| `postgres` (read-only) | dev database only | inspect warehouse, sanity-check ER output; exact package recorded in `.mcp.json` + ADR 0003 |

**Not configured:** anything automating `hq.moh.gov.my` or SSM; broad filesystem
servers (CKAPS PDFs land inside the repo at `data/raw/ckaps/`, so no external
directory access is needed); Google Maps MCP deferred to Phase 1 enrichment work and
subject to the place_id-only rule.

Belt-and-braces: `.claude/settings.json` denies `WebFetch` to `hq.moh.gov.my` and
SSM domains, and denies `Read` of `.env` and `data/**`.
