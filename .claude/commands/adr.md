---
description: Scaffold the next-numbered Architecture Decision Record
argument-hint: [decision title]
---

Create an ADR titled: $ARGUMENTS

1. Find the highest `NNNN` in `docs/decisions/` and use the next number
   (numbering must stay contiguous — checker warning 11).
2. Create `docs/decisions/NNNN-<kebab-slug-of-title>.md`:

```markdown
# NNNN — <Title>

Date: <today> · Status: proposed

## Context

<the forces at play — what makes this a real decision with alternatives>

## Decision

<what we chose, and the alternatives rejected with one line each on why>

## Consequences

<what becomes easier, what becomes harder, what would trigger revisiting>
```

3. Keep it short and honest; flag uncertainty rather than asserting it.
4. Reference the ADR number in the commit that implements the decision.
