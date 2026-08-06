---
title: Architecture
owner: thiran
last_verified: 2026-08-06
verify_by: 2026-11-04
covers_paths:
  - src/grid/**
status: current
---

# Architecture

GRID is a batch discovery pipeline feeding an engagement API. Stages, in order:

```
sources (adapters)          one module per source, uniform contract (below)
   │  fetch()  → immutable snapshot in data/raw/<source>/<date>/
   ▼
ingest/snapshots + differ   snapshot store; diff = new vs newly-listed-but-old
   ▼
normalise/                  names, addresses, phones (+60 E.164), states
   ▼
classify/gp_filter          GP vs dental/specialist/physio/lab/aesthetic
   ▼                        CKAPS scope column is ground truth
resolve/                    blocking → rapidfuzz matching → golden-record clusters
   ▼
enrich/                     geocoding, recency-signal fusion → opened_confidence
   ▼
panel/suppression           drop clinics already on the PMCare panel
   ▼
score/priority              engagement ranking
   ▼
db/ (Postgres + PostGIS)    golden records + full source provenance
   ▼
api/ (FastAPI)  +  export/xlsx (branded PNM workbook)
```

## Two queues (both first-class)

- **Queue A — new openings.** A record is *genuinely new* only if absent from prior
  CKAPS snapshots **and** corroborated by ≥1 recency signal. Relocations/rebrands
  (phone or practitioner continuity across changed name/address) are updates, not new.
- **Queue B — existing registered GP clinics not on the PMCare panel.** Several
  thousand deep; the volume buffer that guarantees the 40–60/month KPI.

## Source adapter contract

Every module in `src/grid/sources/` implements this (defined in `sources/base.py`,
lands at Phase 1 start):

```python
class SourceMeta(BaseModel):
    key: str  # "ckaps"
    display_name: str
    verdict: Literal["primary", "secondary", "leading_indicator", "low_value"]
    access_mode: Literal["manual_download", "api", "scrape", "purchased"]
    legal_basis: str  # REQUIRED — ToS/robots position + why compliant
    robots_allows_automation: bool
    typical_detection_lag_days: tuple[int, int]
    exposes_personal_data: bool
    gp_filter_available: bool
    refresh_cadence: str
    cost_note: str


class SourceAdapter(ABC):
    meta: SourceMeta

    def fetch(self, run_id: str) -> SnapshotRef: ...  # raw → data/raw/, immutable
    def parse(self, snap: SnapshotRef) -> Iterable[RawClinicRecord]: ...
    def health_check(self) -> HealthStatus: ...  # source still shaped as expected?
```

Notes:
- `ckaps.fetch()` does **not** download — it validates a human-placed snapshot exists in
  `data/raw/ckaps/<YYYY-MM-DD>/` and raises an actionable error pointing at
  `docs/runbooks/monthly-ckaps-refresh.md` if not.
- A failing `health_check` alerts; a source returning zero rows is a **failure**, never
  an empty success.
- Enforced by `scripts/check_context.py`: every adapter must declare `SourceMeta` with a
  non-empty `legal_basis`, and have a row in `data-sources.md`.

## Orchestration

APScheduler + Typer CLI (`src/grid/cli.py`), not Prefect — see ADR 0002. Revisit if
DAG complexity grows (fan-out per state, retry graphs, backfills).

## Module status

Scaffold only as of 2026-08-06: packages exist with `__init__.py`; pipeline modules
(`sources/base.py` onwards) land in Phase 1 per `docs/context/roadmap.md`.
