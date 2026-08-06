---
name: pmcare-brand
description: PMCare brand standards for every generated artefact — XLSX workbooks, Word/PDF documents, PowerPoint decks and the design handoff. Arial, Navy #1F4E79 / Teal #16A085 palette, navy table headers with white bold text, branded title slides, status colours. Use whenever producing or styling any xlsx, docx, pptx, PDF or outward-facing document from this project.
---

# PMCare brand

Canonical tokens (mirrored in `docs/context/brand.md` — keep both in sync):

## Typography

Arial throughout — headings and body. No substitutes.

## Palette

| Token | Hex |
|---|---|
| Navy Blue — primary | `#1F4E79` |
| Teal — secondary | `#16A085` |
| Dark Gray — accent | `#2D3748` |
| Header Blue — header text | `#2C5282` |
| Status Green | `#10B981` |
| Status Amber | `#F59E0B` |
| Status Red | `#EF4444` |
| Status Blue | `#3B82F6` |

## Application rules

- **Tables (incl. openpyxl workbooks):** header row filled Navy `#1F4E79`, text
  white + bold; body rows Arial; status cells use the four status colours.
- **Decks:** open with a branded title slide — logo, title, date. Headers in
  Header Blue `#2C5282`.
- **All artefacts:** British/Malaysian English; RM for currency; dates
  DD Month YYYY.
- Every outward-facing artefact is a **draft requiring human review** — say so on
  the artefact itself (footer or cover note).
- Positioning: PMCare is a neutral TPA. Never produce copy implying PMCare makes
  clinical decisions or bears insurance risk (CLAUDE.md guardrail 9).
- The XLSX export implementation lives in `src/grid/export/xlsx.py` (Phase 1) and
  must draw its colours from these tokens, not hardcoded duplicates elsewhere.
