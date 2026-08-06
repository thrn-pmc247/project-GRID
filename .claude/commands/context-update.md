---
description: Identify and update the context docs affected by a change, bumping last_verified
argument-hint: [diff, commit range, or task description]
---

Change under review: $ARGUMENTS

1. Work out which paths the change touches (from the diff/description; use
   `git diff --stat` if a commit range was given).
2. Map those paths to context files via each file's front-matter `covers_paths`
   (all files listed in `CLAUDE.md`'s context map).
3. For each affected context file: read it, verify every claim that touches the
   changed code, and edit what is no longer true. Move — never delete — guardrail
   content.
4. Bump `last_verified` to today and set `verify_by` no more than 90 days out.
5. Regenerate the manifest (`uv run python scripts/check_context.py --fix`), then
   run the checker plain and get it to exit 0.
6. Apply the Definition of Done: new decisions with alternatives → `/adr`; new
   uncertainty → `docs/context/open-questions.md`.
