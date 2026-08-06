# Runbook — Personal data breach notification (PDPA)

Mandatory breach notification has been in force since **1 June 2025** (PDP
(Amendment) Act 2024). GRID holds limited personal data (the `practitioner` table);
a breach of it triggers this runbook.

> ⚠️ **Verify before relying:** the exact notification deadlines and thresholds must
> be confirmed against the current JPDP guideline at first use — they are tracked in
> `docs/context/open-questions.md` (item 11) and must not be assumed from this
> document. This runbook requires review by PMCare's DPO/compliance before it is
> treated as operational.

## Immediate actions (within hours)

1. **Contain**: revoke exposed credentials, isolate the affected system, stop the
   pipeline (`docker compose stop`, disable scheduled runs).
2. **Preserve evidence**: snapshot logs (structlog JSON), DB access records, and the
   `clinic_source_record` / `practitioner` audit trail. Do not delete anything.
3. **Notify internally**: PMCare DPO (appointment status: open question 5) and the
   business owner. GRID's engineering owner: thiranbarath@pmcare.com.my.

## Assessment

4. Scope: which tables/rows, which data classes (business vs personal), how many
   data subjects, likelihood of harm. Only `practitioner` rows and any personal
   fields incorrectly present elsewhere count as personal data.
5. Record the assessment in writing with timestamps — the notification decision and
   its basis must be defensible.

## Notification

6. DPO decides on notification to the **Personal Data Protection Commissioner
   (JPDP)** and, where required, affected **data subjects**, within the deadlines in
   the current JPDP Data Breach Notification guideline (verify — see banner).
7. Use JPDP's prescribed form/channel (check pdp.gov.my at time of use).

## Afterwards

8. Root-cause analysis → ADR or runbook update; add regression checks.
9. Update `docs/context/compliance-pdpa.md` and bump its `last_verified`.
