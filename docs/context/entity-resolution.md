---
title: Entity Resolution
owner: thiran
last_verified: 2026-08-12
verify_by: 2026-11-10
covers_paths:
  - src/grid/resolve/**
status: current
---

# Entity resolution

Goal: one golden `clinic` record per real-world clinic, with full source provenance in
`clinic_source_record`. Design status: rules agreed (below); implementation is Phase 1.

## Normalise before matching

- **Names** (`normalise/names.py`): strip/standardise `Klinik`, `Poliklinik`,
  `Klinik Perubatan`, `Medical Centre`, `Clinic & Surgery`, `Sdn Bhd`; casefold;
  collapse whitespace/punctuation. Keep the original in `name_variants`.
- **Addresses** (`normalise/addresses.py`): expand abbreviations (Jln→Jalan, Lrg→Lorong,
  Psn→Persiaran…), postcode→state consistency check. See
  `malaysian-data-conventions.md`.
- **Phones** (`normalise/phones.py`): `phonenumbers` → +60 E.164; drop invalid.

## Blocking (in order)

1. `postcode`
2. `phone_e164`
3. normalised-name trigrams

## Matching

`rapidfuzz` token-set ratio + Jaro-Winkler on normalised names, combined with address
similarity and phone agreement into a single confidence score.

| Band | Action |
|---|---|
| ≥ high threshold | auto-merge |
| middle band | human review queue — **never silently merge** |
| below | distinct entities |

Thresholds are tuned in Phase 1 against a hand-labelled pair set (≥100 pairs) with
precision/recall tracked in tests. Suppression false-positive rate is measured on the
same set (Phase 1 acceptance).

## Queue A vs Queue B rule

A record is **genuinely new** (Queue A) only if:
1. absent from all prior MyGeoCKAPS snapshots (matched on `mygeockaps_id`, not fuzzily),
   **and**
2. corroborated by ≥1 `recency_signal`.

Otherwise it is *newly listed but pre-existing* → Queue B.

> **Cold-start caveat (ADR 0004).** Condition 1 is only meaningful once GRID holds two
> or more snapshots. If MyGeoCKAPS carries no registration-date field (open q. 14), the
> clock starts at the first pull and condition 1 cannot distinguish a genuinely new
> clinic from one newly added to the GIS. Until enough snapshot history accrues,
> **condition 2 carries the whole rule** — treat an uncorroborated first-appearance as
> Queue B, never Queue A.

Matching across sources (MyGeoCKAPS ↔ ProtectHealth ↔ Google Places ↔ PMCare panel)
still needs the fuzzy pipeline above; only same-source diffing gets the stable-ID
shortcut.

## Relocations and rebrands

Updates, not new market entrants. Detect via **phone or practitioner continuity**
across a changed address/name. Unhandled, these inflate Queue A — treat as a
first-class matcher case with fixtures.
