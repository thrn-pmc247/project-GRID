# tests/integration

Tests needing the Postgres/PostGIS container (docker compose up -d db) or the full
pipeline wiring: migrations, snapshot ingest → diff → resolve flows. Skipped when
the database is unavailable.
