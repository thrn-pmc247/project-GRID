# 0006 — Target Postgres, build and test offline on SQLite with attached schemas

Date: 2026-08-17 · Status: accepted

Implements the layer model fixed by ADR 0005 and `docs/reconciliation-pr001.md` §8.

## Context

The PR001 layer model is expressed in **real SQL schemas** — `bronze.`, `staging.`,
`core.`, `ops.`, `pii.` — and the boundaries between them are load-bearing, not
decorative:

- `bronze` holds the source verbatim and is the only place quarantined columns
  (`QR_ENCRYPTED_TEXT`, `QR_FILE_PATH`) may exist.
- `staging` is where the five drop-disposition columns leave the pipeline and where
  sentinels are remapped to NULL with a logged count.
- `core` is the analytical layer and must be safe to expose through shareable views.
- `pii` is the segregated personal-data schema required by guardrail 4 and
  `docs/context/compliance-pdpa.md`.
- `ops` carries load and transform logs.

The PDPA tests assert that no restricted column reaches a shareable layer. If that
assertion runs against a database where the layers are only a naming convention, the
test proves less than it appears to.

Two environment facts constrain how this gets built:

1. **There is no database to migrate against.** Open question 2 records that Docker
   Desktop is not installed on this machine, so no Postgres 16 + PostGIS instance
   exists. Zero Alembic migrations have ever been run; `src/grid/db/models.py` holds a
   bare `DeclarativeBase`.
2. **The PR001 work is specified as offline-buildable.** The extract is a local file.
   Nothing in the incumbent path needs the network, and ADR 0004's discovery adapter is
   independently gated on open questions 14–16, so a database prerequisite would stall
   work that has no other blocker.

SQLite is the obvious offline engine, and the usual objection is that it has no schemas.
That objection is wrong in the way that matters: `ATTACH DATABASE ... AS bronze` gives
SQLite genuine schema-qualified names, so `bronze.pr001_provider_master` is a real
qualified reference resolved by the engine, not a table called
`bronze_pr001_provider_master`.

## Decision

**Target PostgreSQL via SQLAlchemy 2.0** — already a main dependency, alongside
`alembic`, `psycopg[binary]` and `geoalchemy2`. Production DDL, migrations and the
eventual PostGIS geometry live there.

**Run offline and in tests on SQLite, with one attached database file per schema.** A
test fixture attaches `bronze`, `staging`, `core`, `ops` and `pii` before any DDL runs,
so schema-qualified names resolve identically in both engines and the model is written
once. No table name is prefixed to fake a layer.

**The coordinate columns are plain floats, not PostGIS geometry.** Latitude and
longitude are stored as nullable doubles beside a `coord_quality` enum (VALID, MISSING,
NULL_ISLAND, OUT_OF_BOUNDS, REPAIRED_DECIMAL, REPAIRED_SPLIT). This is a deliberate
consequence of the offline decision — see the accepted risk below — and is also the
honest representation of a column where only 9,878 of 33,643 rows hold a usable pair
(ADR 0005). A geometry type would have to reject or coerce the other 70.6%; a float pair
plus a quality flag records exactly what is known and exactly what is not.

## Alternatives considered

| Option | Verdict |
|---|---|
| Single schema with table-name prefixes (`bronze_pr001_provider_master`) | **Rejected** — it dissolves the layer boundary the PDPA controls depend on. `GRANT`/`REVOKE` and default-view exclusion both operate on schemas; a prefix is a comment, enforced by nobody. |
| DuckDB for the offline path | **Rejected** — a new runtime dependency for a problem `ATTACH DATABASE` already solves, and a third analytical engine in a project that has just settled on Polars for parquet. |
| Block all PR001 work until Docker Desktop is installed | **Rejected** — the task is specified as offline-buildable and the extract is a local file. Blocking would idle work whose only prerequisite is already met. |
| Build against a hosted Postgres instance | **Rejected for now** — it puts real provider data on a remote host before the PDPA processing register question (open question 5) is answered. Revisit once a sanctioned instance exists. |
| Write the model twice, once per engine | **Rejected** — two definitions drift, and the one the tests exercise would not be the one production runs. |

## Consequences

**Positive**

- Schema-qualified names are exercised by the tests, so the layer boundary is verified
  rather than asserted.
- The whole PR001 path — bronze load, staging conform, core build, PDPA assertions —
  runs with no Docker, no network and no credentials.
- Migrations can be authored and reviewed now and applied to Postgres unchanged when an
  instance appears.
- CI needs no database service container.

**Negative / accepted risks**

- **PostGIS is not exercised offline.** No geometry type, no spatial index, no
  `ST_DWithin` is validated by the test suite. When PostGIS does arrive, the spatial
  layer is genuinely untested code. This is the direct reason coordinates are modelled
  as plain floats behind `coord_quality` for now, and it must be stated in the first
  spatial migration's review.
- **SQLite is a weaker type system.** It will accept values Postgres rejects, so
  type-level bugs can survive the offline suite. Constraint and uniqueness behaviour
  differ at the edges too. A Postgres run remains a release prerequisite.
- **Attach limits.** SQLite's default attached-database limit is small; five schemas fit
  comfortably, but the ceiling is real and should be remembered before a sixth layer is
  proposed.
- Two engine profiles means two code paths in the test fixtures, which is a small
  ongoing maintenance cost.

## Dependency finding recorded with this decision

Parquet reading is now on the critical path, which changes the standing of an existing
dependency without adding one.

- **`polars>=1.0` was already declared** in `pyproject.toml` under the `perf` optional
  extra and already resolved in `uv.lock`. It was simply not installed in `.venv`;
  `uv sync --extra perf` installed polars 1.43.2. **No new dependency was added.**
- **The `perf` extra is now a mislabel.** Reading PR001 is not a performance nicety, it
  is the only way the incumbent path gets its data. `pyproject.toml` should eventually
  promote polars to a main dependency or rename the extra. Flagged here rather than
  changed silently, because dependency changes are the human's call.
- **`pyarrow` is absent and must not be added.** It would be a genuine new dependency
  *and* a second parquet stack in the same project.
- **`pandas` 3.0.5 is installed without pyarrow and therefore cannot read parquet at
  all.** It is not an option for this work regardless of preference.
