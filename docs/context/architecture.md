---
title: Architecture
owner: thiran
last_verified: 2026-08-12
verify_by: 2026-11-10
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
   ▼                        MyGeoCKAPS: stable ID → set difference, not fuzzy match
normalise/                  names, phones (+60 E.164), states
   ▼                        addresses: validation only where geometry is authoritative
classify/gp_filter          specialist-vs-general WITHIN layer 5, plus layer 10
   ▼                        adjudication — dental/hospital excluded by layer
resolve/                    blocking → rapidfuzz matching → golden-record clusters
   ▼
enrich/                     recency-signal fusion → opened_confidence
   ▼                        geocoding only for sources lacking geometry
panel/suppression           drop clinics already on the PMCare panel
   ▼
score/priority              engagement ranking
   ▼
db/ (Postgres + PostGIS)    golden records + full source provenance
   ▼
api/ (FastAPI)  +  export/xlsx (branded PNM workbook)
```

**Spine changed 2026-08-12 (ADR 0004).** The authoritative source is the MyGeoCKAPS
ArcGIS REST service (layer 5), not parsed CKAPS register PDFs. Consequences for these
stages:

- **No PDF stage.** `pdfplumber`, layout inference and OCR risk leave the critical path.
- **`classify/gp_filter` shrinks.** Facility type is separated by layer at source, so
  the module handles the specialist-vs-general split inside layer 5 and adjudicates
  layer 10 (combined premises) — not a full keyword taxonomy.
- **Geocoding is largely obviated** for the spine: records arrive as `esriGeometryPoint`
  at SRID 4326. `enrich/geocode.py` narrows to sources that lack geometry.
- **Diffing gets stronger** if a stable unique ID (`ID_UNIK_PHS`) holds up — new-record
  detection becomes a set difference.

**Gated:** no `mygeockaps` adapter is written until the verification items in
`data-sources.md` are answered — in particular whether a registration-date field
exists. If it does not, "genuinely new" is only inferable by diffing forward from the
first snapshot, and `entity-resolution.md`'s Queue A rule leans entirely on
`recency_signal` corroboration for the first few months.

## Two queues (both first-class)

- **Queue A — new openings.** A record is *genuinely new* only if absent from prior
  MyGeoCKAPS snapshots **and** corroborated by ≥1 recency signal. Until two or more
  snapshots exist, the corroboration half carries the rule on its own
  (`entity-resolution.md`). Relocations/rebrands
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
- `mygeockaps.fetch()` pages the REST service (`MaxRecordCount: 2000`, via
  `resultOffset`/`resultRecordCount`) and writes raw GeoJSON to
  `data/raw/mygeockaps/<YYYY-MM-DD>/`. Its `SourceMeta.legal_basis` cannot be written
  honestly until the access question is settled — which is why the adapter is gated.
- `ckaps_pdf.fetch()` (historical baseline only) does **not** download — it validates a
  human-placed snapshot exists in `data/raw/ckaps/<YYYY-MM-DD>/` and raises an
  actionable error pointing at `docs/runbooks/monthly-ckaps-refresh.md` if not.
- A failing `health_check` alerts; a source returning zero rows is a **failure**, never
  an empty success.
- Enforced by `scripts/check_context.py`: every adapter must declare `SourceMeta` with a
  non-empty `legal_basis`, and have a row in `data-sources.md`.

## Orchestration

APScheduler + Typer CLI (`src/grid/cli.py`), not Prefect — see ADR 0002. Revisit if
DAG complexity grows (fan-out per state, retry graphs, backfills).

## Module status

Scaffold only as of 2026-08-12: packages exist with `__init__.py` and no pipeline
modules are written. `sources/base.py` may be built now; `sources/mygeockaps.py` is
blocked on the ADR 0004 gate. See `docs/context/roadmap.md`.
