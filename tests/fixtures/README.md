# tests/fixtures — SYNTHETIC ONLY

Every fixture in this tree is fabricated. Never place real clinic data, real
registration numbers, real phone numbers or any PII here — redact/synthesise first.
`scripts/check_context.py` (check 13) scans tracked files for NRIC-like patterns;
mobile-number scanning is relaxed under `tests/` but the synthetic-only rule is not.

Phase 1 adds: synthetic CKAPS-style PDF samples for parser tests, labelled entity
pairs for resolver precision/recall, and normalisation rule tables.
