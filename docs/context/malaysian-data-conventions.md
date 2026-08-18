---
title: Malaysian Data Conventions
owner: thiran
last_verified: 2026-08-18
verify_by: 2026-11-16
covers_paths:
  - src/grid/normalise/**
status: current
---

# Malaysian data conventions

Reference for `src/grid/normalise/`. The richer working guide is the
`malaysian-address-normalisation` skill (`.claude/skills/`); this file is the
contract the code must satisfy.

## States — canonical set (16)

Johor, Kedah, Kelantan, Melaka, Negeri Sembilan, Pahang, Perak, Perlis, Pulau Pinang,
Sabah, Sarawak, Selangor, Terengganu, WP Kuala Lumpur, WP Labuan, WP Putrajaya.

Variants to map (non-exhaustive; table-driven in `normalise/states.py`):
Penang / P. Pinang → Pulau Pinang · Malacca → Melaka · N. Sembilan / N9 → Negeri
Sembilan · KL / K.L. / Kuala Lumpur / WPKL → WP Kuala Lumpur · Labuan → WP Labuan ·
Putrajaya → WP Putrajaya.

## Addresses

- Abbreviations to expand: Jln→Jalan, Lrg→Lorong, Psn→Persiaran, Tmn→Taman,
  Kg/Kpg→Kampung, Bt→Batu, PJU/SS/USJ section codes kept verbatim.
- Unit/floor forms: `No. 12A`, `12A-1`, `Lot 5`, `Tingkat Bawah` ≡ `Ground Floor`;
  shoplot addressing (`Blok B-3-2`) is common — preserve the raw string, normalise a
  comparison form.
- Postcodes are 5 digits and map to state (and roughly district). **The authoritative
  postcode→state dataset is an open question** (`open-questions.md`) — well-known
  prefix ranges (e.g. 50xxx–60xxx KL, 40xxx–48xxx Selangor, 88xxx–91xxx Sabah,
  93xxx–98xxx Sarawak) must be verified against a Pos Malaysia-derived dataset before
  the mapping table is coded. Do not invent boundaries.

## Clinic names

- Prefixes/suffixes to standardise: Klinik, Poliklinik, Klinik Perubatan, Klinik
  Keluarga, Medical Centre/Center, Clinic & Surgery, Sdn Bhd, PLT.
- Bahasa Malaysia and English forms of the same clinic are common
  (`Klinik Perubatan Aman` ≡ `Aman Medical Clinic`) — matcher must not rely on word
  order.
- `& Surgery` in Malaysian GP naming means minor procedures, not a surgical centre.

## Phones

`normalise/phones.py` **now exists** (built with the Queue B delivery, ADR 0007). The
contract it implements:

- Normalise to +60 E.164 via `phonenumbers`.
- **The region must resolve to MY.** A number that parses but belongs to another region
  is not Malaysian and is not relabelled as one — a `+65` number stays Singaporean and is
  rejected, rather than being silently absorbed into the panel's contact data.
- **Invalid numbers are dropped, never repaired.** No digit-padding, no prefix-guessing,
  no truncation to a plausible length. An unparsable value is recorded as absent, because
  a repaired phone number is a fabricated one (guardrail 10).
- **Multi-value fields are split**, the first parseable value becomes the primary, and
  the non-primary values are **retained** rather than discarded — a clinic that lists two
  lines has two lines.
- Fixed lines: `03` (KL/Selangor), `04`–`09` regional, `08x` Sabah/Sarawak ranges.
- `01x` numbers are mobiles → **potentially personal data** (sole proprietor rule,
  `compliance-pdpa.md`), classified separately from fixed lines so exports can exclude
  them by default. Never place realistic sample numbers in docs or code — the
  forbidden-strings check (check 13) rejects mobile-shaped literals in any tracked file
  outside `tests/`, which includes docstrings, fixtures kept beside source, and comments.

## Language

British/Malaysian English everywhere (normalise, licence, centre, organisation).
Currency: RM.
