# 0007 — Queue B is derived at read time, banded not scored, and ships without phone numbers

Date: 2026-08-18 · Status: accepted

Builds on ADR 0005 (PR001 is the incumbent spine) and ADR 0006 (offline SQLite with
attached schemas). **Supersedes nothing.** ADR 0005 fixed what the incumbent network is;
this ADR fixes how the first thing PNM can actually use is read back out of it.

Evidence throughout is `docs/reconciliation-pr001.md` and the counts measured on the
built `core.provider_outlet`. No figure below is estimated.

## Context

Queue B is the **volume buffer** for the 40–60 engagements per month KPI: existing
registered GP clinics that are not on the PMCare panel. Queue A — genuinely new openings
— is gated on ADR 0004's open questions 14–16 and cannot ship. Queue B is not gated on
anything: every row it needs is already in the repo, offline, in the incumbent master.

The population is real and it is national:

| Step | Rows |
|---|---|
| GP providers (`PROVIDER_TYPE_CODE = 'GP'`) | 13,552 |
| of which active — by `status_code` | 10,506 |
| of which active — by the point-in-time rule | 10,507 |
| of which already on the PMCare panel | 5,956 |
| **Queue B** | **4,550** |

The two active definitions **already disagree, today, on exactly one row**: a termination
dated 2028-08-05 (`docs/reconciliation-pr001.md` §2.6). One row is a rounding error; a
definition that is wrong in a way that grows is not.

Queue B is contactable and it is spread across the country, so it is a usable work
queue rather than a list:

- **4,183** carry a phone value; **3,848** of those parse as valid Malaysian numbers,
  split **3,463 fixed line / 385 mobile**.
- **4,518** carry at least one address line; **4,411** carry a valid five-digit postcode.
- Selangor 1,114 · Johor 760 · WP Kuala Lumpur 606 · Perak 398 · Pulau Pinang 329 ·
  Kedah 228 · Sabah 214 · Sarawak 172 · Kelantan 169 · Negeri Sembilan 168.

Three sub-populations fall out of the same data and are worth naming, because each one
changes what a caller should say:

- **345 GP providers terminated since 2024-01-01** — a win-back segment, not a Queue B
  entry. They were on the panel and left. **147 of them are still flagged on-panel**,
  which is a contradiction between the flag and the lifecycle status that a human must
  resolve.
- **1,005 call-list rows share a chain base name with an active on-panel outlet** (421 of
  those in chains with three or more). A relationship already exists somewhere in the
  group; that is a different opening line from a cold call.
- **218 rows collide exactly on `(name_normalised, postcode_clean)` with an active
  on-panel row**, **20** carry a closed / duplicate / supersession `REMARKS` signal, and
  **1** is a superseded provider code. The first two are probable duplicates of records
  PMCare already holds and are routed to review; the third is excluded outright.

Both comparison sets are restricted to outlets **active as of the same date**. Colliding
with a long-terminated record is a historical duplicate, not evidence the clinic sits on
the panel today — which is why these figures are slightly below the ones an
activity-blind count produces.

What the data does **not** contain is anything that could train a propensity model.
There is no conversion history in PR001 — no outcome variable of any kind. Clinic size is
absent: `NO_DOCTOR_MALE` and `NO_DOCTOR_FEMALE` are booleans, not counts (open question
30). Ownership type is filled for **1,300 of 33,643** providers (open question 24).

And the delivery format is fixed by the audience. PNM works a call list in Excel. The
Phase 1 acceptance criterion says branded XLSX, and `docs/context/brand.md` says every
outward artefact is a draft requiring human review.

## Decision

**1. Queue B is derived at read time from `core.provider_outlet`. No new tables, no
migration 0002.** The queue is a query plus a workbook writer over the core layer as
ADR 0005 built it. `city_raw` is joined from `staging.provider_outlet` where it is
needed for display; `appointment_date` is already in `core.provider_outlet` and its
year distribution matches `CREATE_DATE` for 2023–2026, so it serves as the recency
proxy without widening the core table.

**2. Membership is decided by the point-in-time activity rule, never
`status_code = 'A'`.** A single set-based `active_as_of_clause()` is extracted and shared
by staging and core so the two layers cannot drift into two definitions of "active". The
rule is evaluated against an explicit as-of date, so re-running a historical month gives
the answer that month had, not today's.

**3. Rows are banded, not scored.** Four transparent bands — **chain foothold**,
**recent record**, **contactable**, **no valid phone** — and every row carries the reasons
that placed it in its band. A caller can read why a clinic is in front of them.

**4. The default workbook carries no phone numbers at all,** and therefore ships
regardless of how the personal-data questions are answered. A separate contact workbook
is gated behind a config flag defaulting to false **and** an explicit CLI flag — both,
not either — mirroring the `GRID_OUTREACH_SEND_ENABLED` precedent set by guardrail 6.
Mobile numbers are excluded even from the contact workbook by default: the
sole-proprietor rule in `docs/context/compliance-pdpa.md` bites on exactly those 385
rows, where a dual-use mobile is the practitioner's personal data.

**5. Suppression is a filter, not a fuzzy match.** `PMCARE_PANEL_STATUS` is authoritative
on the incumbent row (restructure R2, ADR 0005), so "already on panel" is read, not
inferred. Superseded provider codes are excluded using the **same exclusion
`core.v_kpi_appointments_monthly` already applies**, so the queue and the KPI cannot
disagree about which record is the live one. The 218 exact `(name_normalised, postcode)`
collisions with an active on-panel row are routed to **review**, not to a caller.

## Alternatives considered

| Option | Verdict |
|---|---|
| A persisted `core.queue_b` table plus migration 0002 | **Rejected** — it creates a staleness problem (the table is right only until the next PR001 refresh) and a second place to get suppression wrong. A derived query is correct by construction every time it runs. |
| Add `city_raw` and `create_date` to `core.provider_outlet` | **Rejected** — `city_raw` is joined from staging where it is needed, and `appointment_date` is already in core with a year distribution matching `CREATE_DATE` for 2023–2026. Widening a core table to avoid one join is the wrong trade. |
| `status_code = 'A'` as the membership test | **Rejected** — `TERMINATION_DATE` reaches 2028-08-05, so the two definitions disagree on one row **today** and the disagreement grows as future-dated terminations mature. It also silently returns the wrong answer for any historical re-run. |
| Two active-row definitions, one in staging and one in core | **Rejected** — they drift, and the drift is invisible until a count disagrees. One `active_as_of_clause()`, used by both. |
| A numeric 0–100 propensity score | **Rejected** — PR001 has **no outcome variable**: no conversion history to fit against. Clinic size is unavailable (`NO_DOCTOR_*` are booleans) and ownership is filled for 1,300 of 33,643 rows. Any weights would be exactly the plausible guess guardrail 10 forbids, dressed as arithmetic. |
| Ship one workbook containing phone numbers | **Rejected** — it makes the whole deliverable wait on the DPO, and the KPI does not wait. Splitting it lets the queue ship now and the contact sheet ship when it is cleared. |
| Include mobile numbers by default in the contact workbook | **Rejected** — 385 of the 3,848 valid numbers are mobiles, and a sole proprietor's mobile is personal data under PDPA 2010 (as amended 2024). Opt-in, never default. |
| Fuzzy-match Queue B rows against the panel to catch near-duplicates | **Rejected as the suppression mechanism** — `PMCARE_PANEL_STATUS` is authoritative on PMCare's own side, so a fuzzy matcher there would be less accurate than the flag it replaced. Exact `(name_normalised, postcode)` collisions are surfaced for review instead. |
| Wait for MyGeoCKAPS (ADR 0004) so Queue A and Queue B ship together | **Rejected** — Queue B is entirely offline and blocked on nothing. Holding it back would idle the only queue that can carry the KPI in a slow month. |

## Consequences

**Positive**

- **The Phase 1 Queue B acceptance criterion is met** with a 4,550-row national queue,
  from data already in the repo, with no database service and no network.
- **The queue cannot silently disagree with the KPI.** Both apply the same supersession
  exclusion and the same activity rule.
- **The deliverable is not blocked on a compliance answer.** The default workbook holds
  no personal data, so it ships while open questions on the call sheet are outstanding.
- **Bands are explainable to a PNM colleague** in one sentence each, and every row states
  its own reasons. A score of 73 is not explainable and would invite exactly the
  false confidence guardrail 10 exists to prevent.
- **No migration, so no schema risk.** ADR 0005's 23-table migration remains the only one,
  and Queue B adds nothing to review or roll back.
- The named sub-populations (345 win-backs, 1,005 chain footholds, 238 routed to review)
  make the queue actionable rather than merely long.

**Negative / accepted risks**

- **Queue B is measured against a snapshot, not a feed.** PR001 is vintage 2026-08-05.
  A clinic panelled since the extract appears in the queue wrongly — the harmless
  direction, as ADR 0005 records, but a caller will meet it.
- **Bands are a judgement, not a measurement.** They are transparent and defensible, but
  nobody has yet shown that "chain foothold" converts better than "contactable". Only
  outreach outcomes can settle that, and recording those outcomes is Phase 2 work.
- **Deriving at read time means the queue is recomputed on every export.** At 4,550 rows
  this is free; if Queue A ever pushes the derived set into six figures the decision
  should be revisited rather than assumed to hold.
- **`appointment_date` is a proxy for recency, not a record-creation date.** The year
  distributions agree for 2023–2026 only; nothing is claimed for earlier years, and the
  median appointment year of 4,550 Queue B rows is **2007**.
- **The queue is not "clinics we have never met".** Every one of the 4,550 has an
  appointment date. What "active GP provider, not on panel" means operationally is
  unanswered — appended to `docs/context/open-questions.md` — and it changes both the
  call script and whether these count as net-new against the 40–60 KPI.
- **702 rows have no valid phone** (4,550 less 3,848) and land in the fourth band. They
  need address-based or field contact, which GRID does not supply.
- **The contact workbook, once permitted, is an export of personal data leaving the
  system.** Retention and destruction of an exported call sheet are unanswered and are
  appended as open questions. The flag stays false until they are answered.

## Follow-ups

- Get the five appended open questions answered — particularly the meaning of "active but
  not on panel" and the DPO's position on a call sheet, since one changes the script and
  the other unblocks the contact workbook.
- Resolve the **147 providers that are terminated yet still flagged as on panel**; the
  flag and the lifecycle status contradict each other and one of them is wrong.
- Revisit banding once Phase 2 records engagement outcomes. That is the point at which a
  score stops being a guess — and not before.
