---
name: malaysian-address-normalisation
description: Normalising Malaysian clinic addresses, state names and postcodes — Jalan/Jln, Lorong/Lrg, Persiaran/Psn abbreviations, Taman/shoplot/Tingkat Bawah forms, 5-digit postcode→state mapping, and state-name variants (Penang/P. Pinang/Pulau Pinang, Melaka/Malacca, KL/WPKL). Use whenever writing or reviewing src/grid/normalise/ code, matching addresses, or debugging address/state/postcode data quality.
---

# Malaysian address normalisation

The code contract lives in `docs/context/malaysian-data-conventions.md`; this skill
is the working detail. Keep the two consistent.

## Street-type abbreviations (expand for the comparison form; keep raw verbatim)

| Abbrev | Full |
|---|---|
| Jln | Jalan |
| Lrg | Lorong |
| Psn | Persiaran |
| Tmn | Taman |
| Kg / Kpg | Kampung |
| Bt | Batu |
| Lbh | Lebuh / Lebuhraya (disambiguate by context) |

Section codes (PJU, SS, USJ, Seksyen/Sek.) stay verbatim — they are meaningful
identifiers, not abbreviations.

## Unit/floor/shoplot forms

- `No. 12A`, `12A-1`, `Lot 5`, `Blok B-3-2` — preserve raw; strip punctuation and
  case for the comparison form.
- `Tingkat Bawah` ≡ `Ground Floor` ≡ `G/F` — treat as equivalent when matching.
- The same shoplot often appears with and without the block/unit prefix across
  sources — address similarity must tolerate a missing unit component.

## States — canonical set (16)

Johor, Kedah, Kelantan, Melaka, Negeri Sembilan, Pahang, Perak, Perlis,
Pulau Pinang, Sabah, Sarawak, Selangor, Terengganu, WP Kuala Lumpur, WP Labuan,
WP Putrajaya.

Variants: Penang / P. Pinang → Pulau Pinang · Malacca → Melaka · N. Sembilan / N9 →
Negeri Sembilan · KL / K.L. / Kuala Lumpur / WPKL → WP Kuala Lumpur · Labuan →
WP Labuan · Putrajaya → WP Putrajaya. The mapping is table-driven in
`normalise/states.py` with a test case per variant.

## Postcodes

5 digits; the first two digits broadly identify the state (e.g. 50xxx–60xxx around
KL, 40xxx–48xxx Selangor, 10xxx–14xxx Pulau Pinang, 80xxx–86xxx Johor, 88xxx–91xxx
Sabah, 93xxx–98xxx Sarawak). **These folkloric ranges are for sanity checks only —
the coded mapping table must come from an authoritative Pos Malaysia-derived
dataset** (open question 12). Use postcode↔state disagreement as a data-quality
flag, not an auto-correction.

## Matching guidance

Normalise → compare with token-based fuzzy matching (rapidfuzz token-set), never raw
string equality. Postcode is the first blocking key
(`docs/context/entity-resolution.md`).
