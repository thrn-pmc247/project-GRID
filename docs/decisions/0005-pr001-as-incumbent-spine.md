# 0005 — PR001 is the incumbent spine and the resolution target

Date: 2026-08-17 · Status: accepted

Complements ADR 0004; **supersedes nothing**. MyGeoCKAPS layer 5 remains the Phase 1
*discovery* spine. This ADR fixes the other side of the join — the network PMCare
already has — and the keys, blocking strategy and table shape that follow from it.

Evidence throughout is `docs/reconciliation-pr001.md`, which profiles the extract
column by column. No figure below is estimated.

## Context

Until now the data model held a single golden `clinic` record per real-world clinic
(`docs/context/data-model.md` as written on 2026-08-12). That design had never met the
PMCare provider master. It has now.

`PR001.parquet` is an extract of PMCare's provider master: **33,643 rows × 70 columns**,
extract vintage **2026-08-05** (max `SYS_TIME_STAMP` 2026-08-05 19:17:18.440). It is not
another discovery source. It is the incumbent register — the thing GRID suppresses
against, the thing Queue B is defined as the complement of, and the baseline the KPI is
measured from. Every discovered candidate must be resolved *against* it before it can be
called new.

Three facts in the extract determine how that resolution can be built:

1. **Two columns are unique across all 33,643 rows and nothing else is.**
   `PROVIDER_CODE` is 33,643/33,643 distinct; `ROW_GUID` is 33,643/33,643 distinct.
   `MIX_ROW_ID`, a legacy integer that looks like a key, is **33,628 distinct — 15 rows
   collide**, all within the range 16,170–16,192.
2. **Coordinates cannot carry matching.** Only **9,878 of 33,643 rows (29.4%)** hold a
   plausible Malaysian latitude/longitude pair. 17,525 have a NULL component, 6,210 sit
   at exactly (0, 0), and 30 are otherwise out of bounds. The dominant failure is a
   single imputation sentinel, not scattered noise: (0, 0) accounts for 99.5% of all
   out-of-range values.
3. **Names are not identities.** `PROVIDER_DESCRIPTION` has **3,303 name groups covering
   10,426 rows** — 31% of the master. Two different causes hide there: genuine
   multi-outlet chains that must stay as separate rows, and the same premises keyed
   twice. 4,155 names end in a parenthesised branch qualifier.

A fourth fact closes off the obvious shortcut. `GST_COMPANY_REG_NO` — the only
SSM-shaped identifier present — holds **125 real values out of 33,643 (0.37%)**, and
those 125 are not consistently registration numbers at all: they mix genuine 12-digit
SSM numbers, old-format hyphenated ones, and at least one company *name*. There is
effectively no SSM linkage in this data, and guardrail 2 forbids acquiring one by
scraping.

## Decision

**1. PR001 is the incumbent master and the resolution target.** It loads into
`bronze.pr001_provider_master` verbatim, is conformed in `staging.provider_outlet`, and
becomes `core.provider_outlet` — the incumbent network. `core.provider_outlet` is
written **from staging only**. GRID never writes a discovered clinic into it.

**2. ADR 0004 stands.** MyGeoCKAPS layer 5 remains the Phase 1 discovery spine and the
gate on open questions 14–16 is unchanged. Discovery finds what PR001 lacks; PR001 says
what discovery must not re-offer. The two ADRs describe opposite sides of the same join,
and neither is a substitute for the other.

**3. `PROVIDER_CODE` and `ROW_GUID` are the only safe keys.** `PROVIDER_CODE` is the
business key carried through every layer; `ROW_GUID` is the source-row identity used for
provenance. `MIX_ROW_ID` is retained as a **nullable, non-indexed passthrough column with
no constraint** and **must never appear in a join, an index or a constraint** — 15
colliding rows would silently duplicate or silently drop.

**4. The blocking key for entity resolution is `name_normalised + postcode`.**
Normalisation strips corporate suffixes and the parenthesised branch qualifier before
grouping. Coordinates are **confirmatory only** and are read solely when
`coord_quality = 'VALID'` on **both** sides of the comparison. Chain membership is
inferred with a confidence value in `core.outlet_chain_member`; it is never asserted.

**5. Incumbent and candidate are separate tables joined by an explicit edge.**
`core.provider_outlet` (incumbent) and `core.grid_candidate` (discovered) share the same
field shape and the same `coord_quality` enum so they stay comparable field-for-field;
`core.outlet_candidate_link` records each resolution decision with its score, method,
blocking key and decider. Human decisions are immutable and always override algorithmic
ones. Detail in `docs/context/data-model.md`.

## Alternatives considered

| Option | Verdict |
|---|---|
| Coordinate-primary matching | **Rejected** — only 9,878/33,643 rows (29.4%) carry a usable coordinate pair. A matcher that leads with geometry is blind to 70.6% of the incumbent master. Coordinates are demoted to a confirmatory signal behind a quality gate. |
| `MIX_ROW_ID` as the key | **Rejected** — 33,628 distinct over 33,643 rows; 15 collide in the range 16,170–16,192. A key that is 99.96% unique is not a key, and the failure mode is silent. |
| SSM company-registration linkage | **Rejected** — 125 real values (0.37%), of inconsistent format, including a company *name* rather than a number. There is no SSM linkage to lean on and no permitted route to one (guardrail 2). |
| Name-only matching | **Rejected** — 3,303 name groups cover 10,426 rows (31%). `name_canonical` alone can never be an identity key; it needs postcode to block on. |
| A single conflated `clinic` table | **Rejected** — it cannot express incumbent versus candidate, which is the structural fact the whole project turns on. One golden record would force GRID's discoveries and PMCare's panel into the same row before anyone had decided they were the same clinic. |
| Defer PR001 until MyGeoCKAPS clears its gate (ADR 0004) | **Rejected** — the incumbent side is offline, already in hand, and blocks nothing. Building it now removes it from the critical path of the gated adapter. |

## Consequences

**Positive**

- Suppression becomes exact rather than probabilistic on PMCare's own side:
  `PMCARE_PANEL_STATUS` is a first-class flag on the incumbent row (GP + status `A` +
  panel = 5,956 rows), so PMCare panel state is authoritative, not observed. This is why
  `panel_membership` narrows to non-PMCare panels (restructure R2).
- Queue B has a denominator. The 33,643-row master defines what "not yet on panel"
  measures against.
- `APPOINMENT_DATE` (0 NULL, 1995-05-02 to 2026-08-05) supplies a real KPI baseline via
  `core.v_kpi_appointments_monthly`, replacing an assumed one.
- Resolution decisions become auditable rows rather than an overwritten field. A
  reviewer can ask why any candidate was suppressed and get an answer.
- The incumbent side is entirely offline, so it progresses while ADR 0004's gate is shut.

**Negative / accepted risks**

- **Recall on the incumbent side will be imperfect and we will not know by how much.**
  Blocking on `name_normalised + postcode` misses a clinic whose postcode is wrong — 185
  of 32,834 populated postcodes do not match `^\d{5}$` — or whose name was keyed
  differently. There is no second identifier to fall back on. Measured precision/recall
  against a labelled pair set is required before the queues are trusted.
- **Coordinates stay largely unusable until repaired**, and the repair rule itself is an
  unapproved item (`docs/reconciliation-pr001.md` §5, item A1). Until then the coordinate
  confirmation step is available for well under a third of comparisons.
- **The extract is a snapshot, not a feed.** Vintage 2026-08-05, refreshed by whatever
  process produces PR001. Staleness between refreshes shows up as false Queue B entries
  (a clinic panelled since the extract) — the least harmful direction, but real.
- **Chain inference can be wrong in both directions**, merging two genuinely separate
  clinics or splitting one chain across spellings. It carries a confidence and never
  gates suppression on its own.
- **Nine of the 70 columns have no confirmed meaning** and seven more are read from their
  names only. Those are the PR001 items in `docs/context/open-questions.md`; none is
  resolved by guessing.
- Two tables now hold clinic-shaped rows. Any query that forgets the distinction gets a
  wrong answer, so the shareable views must make the incumbent/candidate split explicit.

## Follow-ups

- Answer the PR001 open questions with the PNM team — particularly whether `HBRN` is the
  MOH/PHFSA facility registration number, since a confirmed regulator identifier would
  give resolution the second key it currently lacks.
- Decide the coordinate repair rule (item A1) before any coordinate-confirmed match is
  admitted into production scoring.
- Build the labelled pair set that makes blocking recall measurable rather than assumed.
