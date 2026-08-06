# data/ — GITIGNORED ENTIRELY

Nothing in this tree is ever committed (only this README is tracked, via a
`.gitignore` exception). Real clinic data, PII, exports and databases must never
enter git — `scripts/check_context.py` check 13 additionally scans tracked files
for NRIC-like patterns and Malaysian mobile numbers.

| Directory | Contents |
|---|---|
| `raw/` | Immutable source snapshots, e.g. `raw/ckaps/<YYYY-MM-DD>/<state>.pdf` (human-downloaded — see `docs/runbooks/monthly-ckaps-refresh.md`) |
| `interim/` | Parsed/normalised intermediates |
| `exports/` | Generated PNM workbooks and other outputs |

Test fixtures live in `tests/fixtures/` and are **synthetic only**.
