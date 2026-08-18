---
title: Entity Resolution
owner: thiran
last_verified: 2026-08-18
verify_by: 2026-11-16
covers_paths:
  - src/grid/resolve/**
status: current
---

# Entity resolution

Goal: **one incumbent row and one candidate row per real-world clinic, joined by an
explicit, auditable resolution edge** — with full source provenance in
`clinic_source_record`.

> **Corrected 2026-08-18.** This file previously stated the goal as "one golden `clinic`
> record per real-world clinic". Restructure **R1** in ADR 0005 retired that: a single
> conflated record cannot express *incumbent master* versus *discovery candidate*, which
> is the structural fact the project turns on. `clinic` splits into
> `core.provider_outlet` (incumbent, written from staging only),
> `core.grid_candidate` (discovered) and `core.outlet_candidate_link` (the resolution
> edge, carrying score, method, blocking key and decider; human decisions are immutable
> and override algorithmic ones). Both sides keep the same field shape and the same
> `coord_quality` enum so they stay comparable field-for-field.

Design status: rules agreed (below); implementation is Phase 1.

## Normalise before matching

- **Names** (`normalise/names.py`): strip/standardise `Klinik`, `Poliklinik`,
  `Klinik Perubatan`, `Medical Centre`, `Clinic & Surgery`, `Sdn Bhd`; casefold;
  collapse whitespace/punctuation. Keep the original in `name_variants`.
- **Addresses** (`normalise/addresses.py`): expand abbreviations (Jln→Jalan, Lrg→Lorong,
  Psn→Persiaran…), postcode→state consistency check. See
  `malaysian-data-conventions.md`.
- **Phones** (`normalise/phones.py`, **now built** — ADR 0007): `phonenumbers` → +60
  E.164, region must resolve to MY, invalid dropped and never repaired, multi-value
  fields split with non-primary values retained. See `malaysian-data-conventions.md`.

## Blocking (in order)

**Primary blocking key: `name_normalised + postcode`** (ADR 0005). Revised 2026-08-17
after profiling the PR001 incumbent master, which is the reconciliation target:

1. `name_normalised` + `postcode` — the primary key pair
2. `postcode` alone — widens recall where a name is badly spelled
3. normalised-name trigrams

**Coordinates are a confirmatory signal only**, and only when
`coord_quality = 'VALID'` on **both** sides. A coordinate-primary matcher is rejected
outright: just 9,878 of PR001's 33,643 rows (29.4%) carry a plausible Malaysian pair —
17,525 are NULL and 6,210 are exactly (0,0). Note also that `VALID` means "inside the
bounding rectangle", which also contains Sumatra, Kalimantan and open sea; it is not
proof a point is in Malaysia.

**`phone_e164` stays demoted out of blocking, and `normalise/phones.py` existing does
not change that.** In PR001 the phone column is personal data segregated into the `pii`
schema, so blocking on it would drag personal data into the matcher's hot path for every
candidate comparison. A working normaliser makes the values cleaner; it does not make
them business data. Use phone as a confirmatory signal under elevated access, not as a
blocking key.

**Company registration is unavailable as a key.** PR001 carries an SSM-style number on
125 of 33,643 rows (0.37%), inconsistently formatted, and guardrail 2 forbids sourcing
more. Do not design any matcher around it.

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

### Queue B from PR001 — the incumbent-derived definition (ADR 0007)

The rule above defines Queue B **for a discovered candidate**. There is a second,
larger and entirely offline population that needs no matcher at all: GP providers
already in the incumbent master, active, and flagged as not on the PMCare panel.

**Membership test** — all four, evaluated against `core.provider_outlet`:

1. `provider_type_code = 'GP'` (guardrail 7; the 14 unresolved discipline codes stay out
   — open question 27),
2. active by the **point-in-time rule**, never `status_code = 'A'`. The two definitions
   already disagree on one row because `TERMINATION_DATE` reaches 2028-08-05, and the
   disagreement grows. One `active_as_of_clause()` is shared by staging and core so they
   cannot drift apart,
3. **not** on the PMCare panel — `PMCARE_PANEL_STATUS` is authoritative on the incumbent
   row (restructure R2, ADR 0005), so this is a **filter, not a fuzzy match**,
4. not a superseded provider code — excluded with the **same exclusion**
   `core.v_kpi_appointments_monthly` applies, so the queue and the KPI cannot disagree
   about which record is live.

Measured by the implementation, as at 2026-08-17: 13,552 GP rows → 10,506 active by
status code (**10,507** by the point-in-time rule) → 5,957 active and on panel →
**4,550 not on panel** → **4,311 call list** after routing.

**Where resolution still does work here.** Of the 4,550, **218** collide exactly on
`(name_normalised, postcode_clean)` with an *active* on-panel row, **20** carry a closed /
duplicate / supersession `REMARKS` signal, and **1** is a superseded provider code. The
collisions and flags are probable duplicates of records PMCare already holds and are
routed to **review**, never to a caller — the same never-silently-merge principle as the
middle matching band. The superseded row is excluded outright, by the same exclusion the
KPI view applies. A further **1,005** call-list rows share a chain base name with an
active on-panel outlet (**421** in chains of three or more); chain membership carries a
confidence and is never asserted, so it prioritises a call rather than suppressing one.

> Both comparison sets — on-panel collisions and chain footholds — are restricted to
> outlets that are **active as of the same date**. Colliding with a long-terminated
> record is a historical duplicate, not evidence the clinic is on the panel today.

**Rows are banded, not scored** (ADR 0007). PR001 carries no conversion outcome, no
clinic size (`NO_DOCTOR_*` are booleans) and ownership for 1,300 of 33,643 rows, so a
numeric propensity score would be weighted by guesswork. Four transparent bands —
chain foothold, recent record, contactable, no valid phone — each row carrying its
reasons.

## Relocations and rebrands

Updates, not new market entrants. Detect via **phone or practitioner continuity**
across a changed address/name. Unhandled, these inflate Queue A — treat as a
first-class matcher case with fixtures.
