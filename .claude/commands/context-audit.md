---
description: Run the context hygiene checker, summarise findings, propose and apply fixes
---

Run `uv run python scripts/check_context.py --report` and act on it:

1. Summarise findings grouped by severity (FAIL first).
2. For every FAIL, propose the concrete fix: which file, which edit, and why.
3. Apply mechanical fixes directly (regenerate the manifest with
   `uv run python scripts/check_context.py --fix`, repair dead links, add missing
   pointer-table rows).
4. **Never bump `last_verified` without actually re-verifying the document against
   the code in its `covers_paths`** — a blind bump defeats the entire system. If
   the doc is stale, update its content first.
5. Re-run the checker until it exits 0, or report exactly what needs the human
   (and add it to `docs/context/open-questions.md`).
