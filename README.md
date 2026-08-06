# Project GRID — GP Registry & Intelligence Database

GRID is PMCare's automated discovery pipeline for **new private GP clinics in Malaysia**.
PMCare is a third-party administrator / managed care organisation (TPA/MCO); its Provider
Network Management (PNM) team must engage 40–60 new GP clinics per month. GRID finds them:

1. **Discovers** newly opened and newly registered private GP clinics across all 13 states
   and 3 federal territories (including Sabah and Sarawak).
2. **Extracts and normalises** business contact details and location.
3. **Deduplicates** across sources, resolves entities, and suppresses clinics already on
   the PMCare panel.
4. **Serves** a ranked, filterable engagement queue to the PNM team via an API.

Two queues are first-class: **Queue A** (new openings — time-sensitive, highest conversion)
and **Queue B** (existing registered GP clinics not yet on the PMCare panel — the volume
buffer that guarantees the KPI in a slow month).

Scope is **GP / primary care only** (Klinik Umum / klinik perubatan). Dental, specialist,
physiotherapy, diagnostic labs, hospitals and aesthetics-only clinics are out of scope.

## Quickstart (Windows 11)

```powershell
# 1. Python environment (Python 3.12 via uv)
uv sync --all-groups

# 2. Configuration
Copy-Item .env.example .env    # then edit values — never commit .env

# 3. Database (Postgres 16 + PostGIS, requires Docker Desktop)
docker compose up -d db

# 4. Git hooks
uv run pre-commit install

# 5. Verify everything is green
uv run python scripts/check_context.py
uv run pytest
```

## Where things live

| Path | What |
|---|---|
| `CLAUDE.md` | Agent context router + hard guardrails (read first) |
| `docs/context/` | The project context system — architecture, compliance, conventions |
| `docs/decisions/` | Architecture Decision Records |
| `docs/runbooks/` | Operational procedures (CKAPS refresh, breach notification, triage) |
| `src/grid/` | Pipeline source code |
| `scripts/check_context.py` | Context hygiene gate (runs in pre-commit, CI, and pytest) |
| `data/` | Raw/interim/export data — **gitignored entirely, never committed** |

## Hard rules (see `CLAUDE.md` for the full list)

- Never crawl `hq.moh.gov.my`; CKAPS register PDFs are downloaded manually
  (`docs/runbooks/monthly-ckaps-refresh.md`).
- Never scrape SSM.
- Google Places: persist `place_id` only.
- Business data and practitioner personal data are segregated at schema level (PDPA 2010,
  as amended 2024).
- No real clinic data, PII, exports or secrets in git — ever.
