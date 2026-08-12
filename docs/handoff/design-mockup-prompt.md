# Prompt for Claude Design — GRID mockup interface for the PNM meeting

> Status: pre-Phase-3 concept mockup prompt (drafted 2026-08-11). This is NOT the
> formal `design-brief.md` (that lands in Phase 3, generated against the real API).
> Purpose: a clickable demo for this week's PNM meeting to win buy-in and harvest
> field/filter feedback. Everything below is safe to paste into Claude Design as one
> prompt.

---

## The prompt

You are designing **GRID (GP Registry & Intelligence Database)** — a working, clickable
mockup of a provider-discovery dashboard for PMCare, a Malaysian third-party
administrator (TPA). It will be demoed live to the Provider Network Management (PNM)
team this week. There is no backend yet: build a **single self-contained HTML page**
(inline CSS/JS, embedded synthetic data, no external requests) that runs offline on a
laptop and projects well at 1366×768 and above.

### Who uses it and why

PNM officers must engage **40–60 new GP clinics per month** onto the PMCare panel.
Today they find clinics manually. GRID finds them automatically and serves two queues:

- **Queue A — New openings.** Newly opened clinics detected from early signals
  (job ads, first Google reviews, grand-opening posts, new MOH registrations, SOCSO
  panel additions). Time-sensitive and highest conversion — a brand-new clinic
  actively wants panels. Small (roughly 30–50 candidates a month).
- **Queue B — Existing clinics not yet on the PMCare panel.** Thousands deep. The
  volume buffer that guarantees the monthly KPI when new openings run slow.

User stories to satisfy:

1. As a PNM officer, I open GRID on Monday and immediately see how far the team is
   against this month's 40–60 target.
2. I work Queue A top-down by priority score and can see *why* each clinic is
   believed to be newly opened (evidence chips) before I call.
3. I filter either queue to my territory (state, district/postcode) and to clinics
   detected in the last 14/30/60 days.
4. I open a clinic's detail panel, see its business contact details and source
   provenance, and log a call attempt against it.
5. I assign a clinic to myself so colleagues don't double-call it.
6. When a clinic declines or opts out, I record that and GRID visibly, permanently
   suppresses it.
7. As a PNM lead, I see the month's funnel (new → contacted → engaged) and each
   officer's pipeline at a glance.

### Layout

**Header bar** — GRID wordmark + "PMCare · Provider Network Management", global
search box (clinic name/postcode), and a permanent amber banner:
**"MOCKUP — synthetic data only. Not live pipeline output. Draft for internal
review."** This banner is non-negotiable and must survive screenshots.

**KPI strip** (always visible, top of page):
- "Engaged this month: 23 of 40–60" with a progress bar showing the 40 (minimum)
  and 60 (stretch) markers; bar segments coloured by source queue (A vs B).
- Small 6-month bar chart of monthly engaged counts (synthetic: mix of months that
  hit and one that dipped below 40 — that dip is the product's selling point).
- Counters: "Queue A: 46 candidates" · "Queue B: 3,412 clinics" · "Suppressed
  (already on panel / opted out): 1,208".

**Two tabs: Queue A and Queue B** — same table component, different emphasis.

Queue A columns: Priority score (0–100, sortable, default sort) · Clinic name ·
State · District/City · Detected (days ago) · Opened estimate + confidence
(High/Medium/Low pill) · Evidence (chips: `Job ad` `New MOH registration`
`First Google review` `Grand-opening post` `SOCSO panel add`
`Chain announcement` — each chip tooltips its date) · Status · Assigned to.

Queue B columns: Clinic name · State · District/City · Registered since (year) ·
Competitor panels (small icons/count — e.g. "on 2 other panels") · Priority score ·
Status · Assigned to.

**Filter rail** (left or top): State (all 16 Malaysian states/federal territories —
Johor, Kedah, Kelantan, Melaka, Negeri Sembilan, Pahang, Perak, Perlis,
Pulau Pinang, Sabah, Sarawak, Selangor, Terengganu, WP Kuala Lumpur, WP Labuan,
WP Putrajaya) · Detected within (14/30/60/90 days) · Priority score range · Status ·
Assigned to (Me / Unassigned / anyone) · toggle "Hide opted-out" (default ON, and
switching it off shows opt-outs greyed and uncallable, never re-activated).
Filters and sorting must actually work against the embedded synthetic data.

**Clinic detail drawer** (opens on row click):
- Business details: canonical name (+ "also seen as" name variants), full address,
  postcode, state, main clinic phone line, website, Act 586 registration number,
  operating hours, small static map placeholder with a pin.
- Discovery: first seen date, opened estimate + confidence, evidence timeline
  (each signal with date and a fake source link).
- Provenance: table of source sightings (e.g. "MOH CKAPS register — snapshot
  2026-07-08", "Google Places — refreshed on view", "SOCSO panel list — 2026-07-21")
  with observed dates and match confidence.
- **PDPA affordance:** a locked section titled "Practitioner details — restricted
  (PDPA 2010). Requires elevated access; all access is logged." Greyed, not
  clickable. This deliberately demonstrates that personal data is segregated and
  absent from the default view. Never show practitioner names, MMC numbers,
  personal mobiles or emails anywhere in the mockup.
- Engagement panel: status dropdown (New → Assigned → Contacted → In discussion →
  Engaged / Declined / Opted out), "Assign to me", "Log call attempt" (adds a
  timestamped entry to a visible attempts log), "Record opt-out" (requires a
  confirm dialog warning it is **permanent**; afterwards the clinic row is greyed
  with a red "Opted out — permanently suppressed" badge).
- Outreach buttons for WhatsApp/email appear **disabled** with tooltip: "Disabled
  pending compliance sign-off — outreach is phone-first (published business line
  only)." Do not make them look temporarily broken; make them look deliberately
  gated.

**States to design, reachable in the demo:** loading (skeleton rows on first
paint), empty ("No clinics match these filters" with a one-click Clear filters),
and error (dismissible banner: "Pipeline refresh unavailable — showing data as at
08 August 2026"). Add an unobtrusive "Demo states" control to trigger these live.

### Synthetic data rules (hard requirements)

- Fabricate everything. Clinic names must be plausible in *shape* but obviously
  invented — Bahasa Malaysia and English mixes like "Klinik Delima Contoh",
  "Poliklinik Seri Demo & Surgery", "Klinik Perubatan Contoh Jaya 24 Jam". Never
  use a real clinic's name.
- Addresses use real state names and plausible street patterns (Jalan, Lorong,
  Persiaran, Taman, shoplot forms like "No. 12A, Tingkat Bawah") with fake street
  names; 5-digit postcodes consistent with the state.
- Phone numbers: fixed business lines only, in an obviously fake pattern
  (e.g. `+60 3-0000 0xx` style). **No mobile numbers (no `01x` numbers) anywhere.**
- Registration numbers: clearly fake format, e.g. "CONTOH-0001". No NRIC-like
  numbers anywhere.
- Volume: ~46 Queue A rows spread across all 16 states (include Sabah and Sarawak
  visibly); ~250 Queue B rows labelled "sample of 3,412".
- Currency RM; dates as DD Month YYYY; British/Malaysian English spelling
  throughout (normalise, centre, licence).

### Brand (apply exactly)

- Font: **Arial** throughout.
- Navy Blue `#1F4E79` (primary — header bar, table header rows with **white bold**
  text) · Teal `#16A085` (secondary accents) · Dark Gray `#2D3748` (body emphasis,
  borders) · Header Blue `#2C5282` (section heading text).
- Status colours: Green `#10B981` (engaged/on-track) · Amber `#F59E0B`
  (at-risk/in-discussion) · Red `#EF4444` (declined/opted-out/blocked) · Blue
  `#3B82F6` (new/informational).
- Footer on the page: "PMCare — neutral third-party administrator. Internal draft
  requiring human review. Synthetic data."

### Positioning guardrails (must hold in every pixel of copy)

- PMCare is a **neutral TPA** — never imply it is an insurer, bears insurance risk,
  or makes clinical decisions. No clinical language about patients or treatment.
- No mass-outreach affordances (no "send to all", no broadcast, no bulk WhatsApp/
  email). Outreach is consent-first and phone-first; opt-out is permanent.
- Do not invent statistics presented as real (the KPI numbers are demo values on
  synthetic data — the banner covers this).

### Out of scope for this mockup

Login/auth, real API calls, mobile layout (desktop/projector only), personal-data
views, XLSX export behaviour (a disabled "Export workbook" button with tooltip
"Available in the pipeline build" is fine), and any admin/settings screens.

### Done means

A single HTML file that opens offline, both tabs populated and filterable, KPI strip
rendered, detail drawer opening with provenance + engagement actions working against
the in-page data, opt-out flow demonstrably permanent within the session, the three
demo states triggerable, the synthetic-data banner permanently visible, and brand
tokens applied as specified.

---

## Notes for the demo driver (not part of the Design prompt)

Feedback to harvest from PNM while driving the mockup — these decide the real
Phase 3 build (`docs/context/open-questions.md` items 1, 6, 7):

1. Which columns do officers actually triage by? What's missing / noise?
2. Is the status workflow right, and must GRID feed the existing CRM instead of
   owning engagement state (open question 7)?
3. How is territory really assigned — state, district, or something else?
4. Panel extract: who owns it, what format, how fresh (open question 1 — blocking
   Phase 1)?
5. Does the 40–60 KPI widget match how the team is actually measured?
