---
name: gp-classification
description: Decision rules for classifying a clinic as GP/primary care vs dental, specialist, physiotherapy, diagnostic lab or aesthetics-only — with Bahasa Malaysia and English keyword lists, the CKAPS-scope-overrides-heuristics rule, and the ambiguous-goes-to-review rule. Use whenever writing or reviewing src/grid/classify/gp_filter.py, tuning classification keywords, or deciding whether a specific clinic is in scope for the queues.
---

# GP classification

Scope: **GP / primary care only** (CLAUDE.md guardrail 7). Most sources mix
categories — filtering is first-class.

## Rule 0 — CKAPS scope overrides everything

If the CKAPS register scope column says `Klinik Umum`, the clinic is GP; if it names
a specialist scope, it is not. No heuristic may override the register. Heuristics
below exist for sources without a scope field, and are calibrated against CKAPS.

## Include signals (BM / EN)

klinik umum · klinik perubatan · poliklinik · klinik keluarga · klinik am ·
family clinic · general practice / GP clinic · clinic & surgery / klinik & surgeri
(in Malaysian GP naming, "& Surgery" means minor procedures, not a surgical centre) ·
24 jam / 24 hours (usually GP) · klinik komuniti.

## Exclude signals (BM / EN)

- **Dental:** pergigian · dental · dentist · ortodontik
- **Specialist:** pakar · specialist · ENT/ORL · O&G / obstetrik · kardiologi ·
  oftalmologi / eye / mata · dermatologi (as a specialist centre) · pediatrik
  specialist centre · surgeri (as a true surgical centre) · haemodialisis / dialysis
- **Physio / rehab:** fisioterapi · physiotherapy · rehab centre
- **Labs / imaging:** makmal · lab · patologi · diagnostik · x-ray · imaging ·
  saringan / screening centre
- **Aesthetics-only:** estetik · aesthetic · skin & laser · kecantikan / beauty ·
  slimming
- **Not private GP at all:** Klinik Kesihatan · Klinik Desa · Klinik 1Malaysia
  (government facilities) · veterinar / veterinary · TCM / homeopati / tradisional

## Ambiguity rules

- `klinik pakar` → specialist unless CKAPS scope says otherwise.
- `klinik kanak-kanak` → ambiguous (may be GP-style paediatric primary care) →
  review queue, not auto-exclude.
- GP clinic with an aesthetics side-line → **include** (scope `gp_with_interest`);
  aesthetics-only → exclude.
- Anything the rules cannot decide goes to the **human review queue** — never
  silently classify. Log the deciding keyword(s) for auditability.

## Testing

Every keyword/rule gets a table-driven pytest case (synthetic names). Calibration:
measure the heuristic classifier against CKAPS scope on each new snapshot; a
precision drop is an alert, not a curiosity.
