---
title: PMCare Brand Tokens
owner: thiran
last_verified: 2026-08-18
verify_by: 2026-11-16
covers_paths:
  - src/grid/export/**
status: current
---

# PMCare brand tokens

Applied to every outward artefact GRID produces (XLSX workbooks, docx memos, pptx
decks, the Claude Design handoff brief). Mirrored in the `pmcare-brand` skill.

## Typography

Arial throughout — headings and body.

## Colours

| Token | Hex | Use |
|---|---|---|
| Navy Blue (primary) | `#1F4E79` | titles, table header fills, primary accents |
| Teal (secondary) | `#16A085` | secondary accents, highlights |
| Dark Gray (accent) | `#2D3748` | body emphasis, borders |
| Header Blue | `#2C5282` | header text |
| Status Green | `#10B981` | positive / on-track |
| Status Amber | `#F59E0B` | warning / at-risk |
| Status Red | `#EF4444` | negative / blocked |
| Status Blue | `#3B82F6` | informational |

## Rules

- Table header rows: navy fill (`#1F4E79`), **white bold** text.
- Decks open with a branded title slide: logo, title, date.
- Currency RM; British/Malaysian English spelling.
- Every outward artefact is a **draft requiring human review** — mark it as such.
- PMCare is a neutral TPA: no copy positioning it as insurer or treating clinician.

## XLSX workbooks

`src/grid/export/xlsx.py` is **the** implementation of these tokens for workbooks. Apply
them there; do not re-declare fills, fonts or hexes at each call site.

- **Postcode and state columns must be written as Excel text format (`@`).** Excel
  otherwise reads a postcode as a number and `05000` silently becomes `5000` — a
  data-quality defect introduced by the export, not present in the data.
- **Exports are written to `data/exports/`, never the repo root.** `data/` is gitignored
  in full (guardrail 5), and `check_context.py` check 13 fails the build on a stray
  `*.xlsx` or `*.csv` at the repo root — it globs the filesystem, not the git index, so
  being gitignored does not satisfy it.
- Every workbook opens with a branded cover sheet carrying the title, the generation
  date, the extract vintage it was derived from, a **draft — requires human review before
  use** notice, and the neutral-TPA line.
- Header rows use the navy fill and white bold text above; freeze the header row and set
  an autofilter, because these workbooks are worked, not read.
- A workbook that can contain personal data says so on its cover sheet and names the
  retention expectation. See `compliance-pdpa.md`; the Queue B contact workbook is gated
  by config and CLI flag per ADR 0007.
