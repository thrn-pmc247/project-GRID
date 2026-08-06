---
name: pdpa-review
description: PDPA compliance checklist to run before any change that touches personal data — field classification (business vs personal), lawful basis, retention, access control, sole-proprietor mobile rule, breach-notification implications. Use whenever adding/altering fields or tables holding names, phone numbers, emails or MMC numbers, changing API responses, adding a data source that exposes people, or writing exports/logs that could contain personal data.
---

# PDPA review checklist

Regime: PDPA 2010 (Act 709) as amended by the PDP (Amendment) Act 2024. Full
context: `docs/context/compliance-pdpa.md`. Run every item; record answers in the
PR/commit description.

## 1. Classify every field the change touches

- Business (default): clinic name, business address, postcode, state, main clinic
  line, Act 586 reg no, website, hours.
- Personal: practitioner names, MMC numbers, personal mobiles, personal emails.
- **Edge rule:** a sole proprietor's mobile doubling as the clinic line is
  personal. `01x` numbers are mobiles — treat with suspicion.

## 2. If anything is personal

- [ ] Does it live in the `practitioner` table (or an equally restricted one) —
      never in `clinic`, never in raw JSONB payloads?
- [ ] Is `lawful_basis` recorded per row, and defensible?
- [ ] Is `retention_until` set, with a purge path?
- [ ] Is there a `purpose_note` a regulator could read without wincing?
- [ ] Is it excluded from default API responses (elevated scope + audit log only)?
- [ ] Is it excluded from logs (counts and IDs only) and from exports?

## 3. Source-side

- [ ] Does the source's `SourceMeta.exposes_personal_data` flag match reality?
- [ ] Does parsing strip personal fields before warehousing?

## 4. Blast-radius

- [ ] If this data leaked, does `docs/runbooks/data-breach-notification.md` cover
      it? Would the DPO know what was held and why?
- [ ] Is nothing personal committed to git (fixtures synthetic, `data/`
      gitignored, check 13 green)?

## 5. Outcome

Any "no" blocks the change. Genuine uncertainty → `docs/context/open-questions.md`
and ask the human — never guess a lawful basis. PMCare's DPO/compliance owns final
sign-off; this checklist is engineering hygiene, not legal advice.
