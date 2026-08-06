---
description: Report progress against the current phase's acceptance criteria
---

Read `docs/context/roadmap.md` and report:

1. Current phase and its next milestone.
2. Each acceptance criterion for the current phase with an evidence-based status —
   run `uv run pytest` / `uv run python scripts/check_context.py` where they are
   the evidence. **Never mark a criterion done without evidence.**
3. Blockers, cross-referenced against `docs/context/open-questions.md` (call out
   anything blocking for the current phase).
4. Whether the phase gate is met (a phase does not start until the previous one's
   acceptance criteria all pass).

If reality has drifted from `roadmap.md`, update the roadmap (and its
`last_verified`) as part of this command.
