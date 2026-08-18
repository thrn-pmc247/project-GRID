"""Engagement priority — a transparent ordering, not a fabricated score.

PR001 carries no outcome variable. There is no conversion history, no record of which
clinics were approached and no record of who said yes. There is also no clinic size
(`NO_DOCTOR_MALE` and `NO_DOCTOR_FEMALE` are booleans despite their names), no usable
ownership data (1,300 of 33,643 rows filled) and no revenue proxy. A 0 to 100 propensity
score built on that would be a weighting of guesses wearing the costume of a measurement,
which is exactly what CLAUDE.md guardrail 10 forbids.

So this module produces a **deterministic sort order plus a named band, where every row
carries the reasons that put it there**. A caller can read why a clinic is near the top,
and disagree with it. Nobody is asked to trust a number nobody can explain.

What each signal is worth:

* **Chain foothold** (`chain_on_panel_outlets`) — the warmest signal available, because
  PMCare already panels the brand and there is an existing relationship to lean on. It is
  **inferred** from a shared normalised base name, and a shared name can equally mean the
  same premises keyed twice, so every reason string says "inferred" rather than asserting
  it as fact.
* **Record recency** (`appointment_date`) — weak, and honestly labelled: it is the
  freshness of *PMCare's record*, not of the clinic.
* **Contactability** (`has_valid_phone`) — a clinic with no valid number cannot be phoned,
  so it sorts last. That is not a judgement on the clinic; it is a queue of work (find a
  number) that has to happen before anyone dials.
* **Territory** (`state_code`, `postcode_prefix`) — **routing, not ranking**. It breaks
  ties so that one caller works one area. No state is ever worth more than another.
* **Data confidence** (`postcode_valid`, `postcode_state_mismatch`, the review segments) —
  surfaced as caveats in `reasons`, never as rank.

`coord_quality` is deliberately absent: only 844 of 4,550 call-list rows carry any
coordinate pair at all, so ranking on it would rank on who happened to be geocoded.

Ordering is total and stable — `provider_code` breaks the last tie — so two runs of the
same input produce byte-identical output and month-over-month exports diff cleanly.

Business data only. Contactability enters as a caller-supplied boolean, never as the
number itself, so nothing in this module holds personal data (PDPA 2010, guardrail 4).
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import structlog

from grid.panel.suppression import QueueBRow, Segment

log = structlog.get_logger(__name__)

RECENT_RECORD_YEARS: Final = 2
"""How far back `appointment_date` still counts as a recently added record."""

NO_PHONE_REASON: Final = (
    "no valid phone number on record — a contact number is needed before anyone can call"
)
"""Why band D exists. Stated as work outstanding, not as a mark against the clinic."""

HAS_PHONE_REASON: Final = "a valid phone number is on record"
"""The floor for bands A to C: the clinic can actually be rung."""


class PriorityBand(StrEnum):
    """Which band a row falls in. The label is the explanation."""

    A_CHAIN_FOOTHOLD = "A — chain already on panel"
    """An inferred sibling outlet is already panelled, so there is a relationship."""

    B_RECENT_RECORD = "B — record added recently"
    """PMCare's record is fresh, which is weak evidence the details still hold."""

    C_CONTACTABLE = "C — contactable"
    """Nothing distinguishes this row except that it can be phoned."""

    D_NEEDS_CONTACT = "D — no valid phone number"
    """Unreachable until someone finds a number. Always sorts last."""


_BAND_ORDER: Final[Mapping[PriorityBand, int]] = {
    PriorityBand.A_CHAIN_FOOTHOLD: 0,
    PriorityBand.B_RECENT_RECORD: 1,
    PriorityBand.C_CONTACTABLE: 2,
    PriorityBand.D_NEEDS_CONTACT: 3,
}
"""Explicit rank per band. Never inferred from the label text, which is prose."""


@dataclass(frozen=True, slots=True)
class Priority:
    """A band and the evidence for it. There is deliberately no numeric field."""

    band: PriorityBand
    reasons: tuple[str, ...]
    """Human-readable, specific and ordered: what earned the band first, then caveats.
    Never empty — every row has at least one thing to say for itself."""


def _years_before(as_of: dt.date, years: int) -> dt.date:
    """The same calendar day `years` earlier, stepping 29 February back to the 28th.

    Args:
        as_of: The reference date.
        years: How many whole years to step back.

    Returns:
        The corresponding date in the earlier year.
    """
    try:
        return as_of.replace(year=as_of.year - years)
    except ValueError:
        return as_of.replace(year=as_of.year - years, day=28)


def _recent_record_year(row: QueueBRow, as_of: dt.date) -> int | None:
    """The year PMCare's record was added, if that was recent enough to count.

    Args:
        row: The Queue B row.
        as_of: The date recency is judged against. Never defaulted — a queue is always
            "as at" some date, and leaving it implicit is how historical runs go wrong.

    Returns:
        The year of `appointment_date` when it falls within `RECENT_RECORD_YEARS` of
        `as_of`, otherwise None.
    """
    added = row.appointment_date
    if added is None:
        return None
    if added.date() < _years_before(as_of, RECENT_RECORD_YEARS):
        return None
    return added.year


def _chain_reason(outlets: int) -> str:
    """Phrase the chain foothold, always flagging that the chain itself is inferred.

    Args:
        outlets: How many outlets of the same inferred chain are already on panel.

    Returns:
        A reason string that never asserts chain membership as fact.
    """
    subject = "outlet of this chain is" if outlets == 1 else "outlets of this chain are"
    return (
        f"{outlets} {subject} already on the PMCare panel (inferred from a shared normalised name)"
    )


def _caveats(row: QueueBRow, *, recent_year: int | None) -> tuple[str, ...]:
    """Things a caller should know before dialling. None of these change the band.

    Args:
        row: The Queue B row.
        recent_year: The result of `_recent_record_year`, so record vintage is described
            once rather than judged twice.

    Returns:
        Ordered caveat strings, empty when the row is clean.
    """
    out: list[str] = []

    added = row.appointment_date
    if added is None:
        out.append("no date on PMCare's record — its vintage is unknown")
    elif recent_year is None:
        out.append(f"record last dated {added.year} — the details may be out of date")

    if row.postcode_state_mismatch:
        out.append("postcode disagrees with the state code — verify the address")
    elif not row.postcode_valid:
        out.append("no usable postcode on record — verify the address")

    if row.segment is Segment.REVIEW_LIKELY_ON_PANEL:
        collides = row.collides_with_provider_code or "an outlet already on panel"
        out.append(
            f"name and postcode collide with {collides}, which is already on panel — "
            "probably the same clinic, so check before calling"
        )
    elif row.segment is Segment.REVIEW_FLAGGED:
        flags = ", ".join(row.review_flags) if row.review_flags else "unspecified"
        out.append(f"PNM's own notes flag this record ({flags}) — check before calling")
    elif row.segment is Segment.WIN_BACK and row.termination_date is not None:
        left = row.termination_date.date().isoformat()
        out.append(f"left the panel on {left} — a win-back conversation, not a cold call")

    if row.panel_flag_conflict:
        out.append(
            "flagged on-panel yet carrying a termination date — the two fields contradict "
            "each other, so confirm the status first"
        )

    return tuple(out)


def assign_priority(row: QueueBRow, *, has_valid_phone: bool, as_of: dt.date) -> Priority:
    """Band one row and record why.

    Banding is a cascade, strongest evidence first: an inferred chain foothold, then a
    recently added record, then mere contactability. A row with no valid phone number is
    band D whatever else it has — it cannot be rung today — but it keeps its other
    reasons, so PNM can see which unreachable rows are worth chasing a number for.

    Args:
        row: The Queue B row, carrying business data only.
        has_valid_phone: Whether a usable number exists for this outlet. Supplied by the
            caller as a boolean so no personal data enters this module.
        as_of: The date recency is judged against.

    Returns:
        The band and the ordered reasons for it, caveats last.
    """
    recent_year = _recent_record_year(row, as_of)
    has_chain = row.chain_on_panel_outlets >= 1

    reasons: list[str] = []
    if not has_valid_phone:
        band = PriorityBand.D_NEEDS_CONTACT
        reasons.append(NO_PHONE_REASON)
    elif has_chain:
        band = PriorityBand.A_CHAIN_FOOTHOLD
    elif recent_year is not None:
        band = PriorityBand.B_RECENT_RECORD
    else:
        band = PriorityBand.C_CONTACTABLE

    if has_chain:
        reasons.append(_chain_reason(row.chain_on_panel_outlets))
    if recent_year is not None:
        reasons.append(
            f"record added {recent_year} — the freshness of PMCare's record, not of the clinic"
        )
    if has_valid_phone:
        reasons.append(HAS_PHONE_REASON)
    reasons.extend(_caveats(row, recent_year=recent_year))

    return Priority(band=band, reasons=tuple(reasons))


def priority_key(row: QueueBRow, priority: Priority) -> tuple[object, ...]:
    """The sort key behind the queue order.

    Ordered by band, then by the two ranking signals (more on-panel siblings first, more
    recently added record first), then by territory so one caller works one area, and
    finally by `provider_code` so the order is total. That last tie-break is what makes
    two runs byte-identical and month-over-month exports diff cleanly.

    Territory is a tie-break only. It groups a queue into workable rounds; it never says
    one state matters more than another.

    Args:
        row: The Queue B row.
        priority: The priority assigned to that row.

    Returns:
        An ascending sort key. Every element is comparable with the same element of any
        other key produced by this function.
    """
    added = row.appointment_date
    return (
        _BAND_ORDER[priority.band],
        -row.chain_on_panel_outlets,
        0 if added is None else -added.date().toordinal(),
        row.state_code,
        row.postcode_prefix is None,
        row.postcode_prefix or "",
        row.provider_code,
    )


def rank(
    rows: Sequence[QueueBRow], phones: Mapping[str, bool], *, as_of: dt.date
) -> tuple[tuple[QueueBRow, Priority], ...]:
    """Band and order a whole queue.

    Args:
        rows: The queue to rank, in any order — the result does not depend on it.
        phones: `provider_code` to "a valid phone number exists". A code absent from the
            mapping is treated as having no valid number: not knowing of a number and
            knowing of no number are the same thing to a caller with a handset.
        as_of: The date recency is judged against.

    Returns:
        Each row paired with its priority, ordered by `priority_key`.
    """
    ranked: list[tuple[QueueBRow, Priority]] = []
    for row in rows:
        reachable = phones.get(row.provider_code, False)
        ranked.append((row, assign_priority(row, has_valid_phone=reachable, as_of=as_of)))
    ranked.sort(key=lambda pair: priority_key(pair[0], pair[1]))

    bands = Counter(priority.band.name for _, priority in ranked)
    log.info(
        "priority.ranked",
        as_of=as_of.isoformat(),
        rows=len(ranked),
        bands={name: bands[name] for name in sorted(bands)},
    )
    return tuple(ranked)
