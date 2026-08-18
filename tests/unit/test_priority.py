"""Table-driven cases for engagement priority banding and queue ordering.

Every row here is fabricated (`KLINIK CONTOH ...`, `GRIDGP0001`), in the style of
`scripts/seed_synthetic.py`. Nothing reads `PR001.parquet` or touches a database — these
are pure-function tests over a dataclass, and real clinic data never belongs in a
repository (CLAUDE.md guardrail 5).

The assertions that matter most are the ones about *honesty*: that a chain reason always
says "inferred", that a data-quality caveat never silently changes a band, and that two
runs of the same input produce the identical sequence so month-over-month exports diff
cleanly.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import pytest

from grid.panel.suppression import QueueBRow, Segment
from grid.score.priority import (
    HAS_PHONE_REASON,
    NO_PHONE_REASON,
    Priority,
    PriorityBand,
    assign_priority,
    priority_key,
    rank,
)

AS_OF = dt.date(2026, 8, 17)
"""Pinned reference date, so recency assertions never drift with the wall clock."""

RECENT_RECORD = dt.datetime(2026, 1, 15)
"""Comfortably inside the two-year window."""

OLD_RECORD = dt.datetime(2019, 2, 2)
"""Comfortably outside it."""

CUTOFF_RECORD = dt.datetime(2024, 8, 17)
"""Exactly two years before `AS_OF`. The window is inclusive, so this still counts."""

JUST_STALE_RECORD = dt.datetime(2024, 8, 16)
"""One day the wrong side of the cutoff."""


def make_row(
    provider_code: str = "GRIDGP0001",
    *,
    name: str = "KLINIK CONTOH SATU",
    chain_on_panel_outlets: int = 0,
    chain_base_name: str | None = None,
    appointment_date: dt.datetime | None = OLD_RECORD,
    termination_date: dt.datetime | None = None,
    state_code: str = "SL",
    postcode: str | None = "40000",
    postcode_valid: bool | None = None,
    postcode_state_mismatch: bool | None = False,
    segment: Segment = Segment.NOT_ON_PANEL,
    collides_with_provider_code: str | None = None,
    review_flags: tuple[str, ...] = (),
    panel_flag_conflict: bool = False,
) -> QueueBRow:
    """Build one fabricated Queue B row.

    Defaults give the dullest possible row: no chain foothold, a stale record, a clean
    postcode. Each test opts into exactly the one signal it is about.

    Args:
        provider_code: Fabricated code, `GRIDGP...` by convention.
        name: Fabricated clinic name.
        chain_on_panel_outlets: Inferred on-panel siblings.
        chain_base_name: The inferred chain, defaulted to the name when siblings exist.
        appointment_date: When PMCare's record was added.
        termination_date: When the outlet left the panel, if it did.
        state_code: Two-letter state code, used for territory routing.
        postcode: Five-digit postcode, or None when there is none on record.
        postcode_valid: Defaulted to "valid when a postcode is present", so the row
            cannot contradict itself.
        postcode_state_mismatch: Whether postcode and state code disagree.
        segment: Which suppression segment routed this row.
        collides_with_provider_code: The on-panel code this row collides with.
        review_flags: REMARKS signals attached to this row.
        panel_flag_conflict: Terminated yet still flagged on-panel.

    Returns:
        A fully populated `QueueBRow`.
    """
    return QueueBRow(
        provider_code=provider_code,
        name_raw=name,
        name_normalised=name,
        chain_base_name=chain_base_name or (name if chain_on_panel_outlets else None),
        branch_qualifier=None,
        address_unit="NO. 1",
        address_street="JALAN CONTOH 1/1",
        address_locality="TAMAN CONTOH",
        city_raw="BANDAR CONTOH",
        postcode_clean=postcode,
        postcode_valid=(postcode is not None) if postcode_valid is None else postcode_valid,
        postcode_prefix=postcode[:2] if postcode else None,
        postcode_state_mismatch=postcode_state_mismatch,
        state_code=state_code,
        appointment_date=appointment_date,
        termination_date=termination_date,
        segment=segment,
        chain_on_panel_outlets=chain_on_panel_outlets,
        collides_with_provider_code=collides_with_provider_code,
        review_flags=review_flags,
        panel_flag_conflict=panel_flag_conflict,
    )


def codes(ranked: Sequence[tuple[QueueBRow, Priority]]) -> tuple[str, ...]:
    """The provider codes of a ranked queue, in order."""
    return tuple(row.provider_code for row, _ in ranked)


def all_reachable(rows: Sequence[QueueBRow]) -> dict[str, bool]:
    """A phone mapping in which every row is contactable."""
    return {row.provider_code: True for row in rows}


# --------------------------------------------------------------------------------------
# Banding
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("chain_outlets", "appointment_date", "has_valid_phone", "expected"),
    [
        # A — an inferred chain foothold beats everything else on offer.
        (3, RECENT_RECORD, True, PriorityBand.A_CHAIN_FOOTHOLD),
        (1, OLD_RECORD, True, PriorityBand.A_CHAIN_FOOTHOLD),
        (1, None, True, PriorityBand.A_CHAIN_FOOTHOLD),
        # B — no foothold, but PMCare's record is fresh.
        (0, RECENT_RECORD, True, PriorityBand.B_RECENT_RECORD),
        (0, CUTOFF_RECORD, True, PriorityBand.B_RECENT_RECORD),
        # C — reachable, and nothing else to say.
        (0, JUST_STALE_RECORD, True, PriorityBand.C_CONTACTABLE),
        (0, OLD_RECORD, True, PriorityBand.C_CONTACTABLE),
        (0, None, True, PriorityBand.C_CONTACTABLE),
        # D — no number, whatever else the row has going for it.
        (3, RECENT_RECORD, False, PriorityBand.D_NEEDS_CONTACT),
        (1, OLD_RECORD, False, PriorityBand.D_NEEDS_CONTACT),
        (0, RECENT_RECORD, False, PriorityBand.D_NEEDS_CONTACT),
        (0, OLD_RECORD, False, PriorityBand.D_NEEDS_CONTACT),
        (0, None, False, PriorityBand.D_NEEDS_CONTACT),
    ],
)
def test_band_assignment(
    chain_outlets: int,
    appointment_date: dt.datetime | None,
    has_valid_phone: bool,
    expected: PriorityBand,
) -> None:
    """The banding cascade, exhaustively."""
    row = make_row(chain_on_panel_outlets=chain_outlets, appointment_date=appointment_date)
    priority = assign_priority(row, has_valid_phone=has_valid_phone, as_of=AS_OF)
    assert priority.band is expected


@pytest.mark.parametrize(
    ("appointment_date", "expected"),
    [
        (dt.datetime(2024, 8, 18), PriorityBand.B_RECENT_RECORD),
        (CUTOFF_RECORD, PriorityBand.B_RECENT_RECORD),
        (JUST_STALE_RECORD, PriorityBand.C_CONTACTABLE),
    ],
)
def test_recency_window_boundary_is_inclusive(
    appointment_date: dt.datetime, expected: PriorityBand
) -> None:
    """Two years to the day still counts; a day earlier does not."""
    row = make_row(appointment_date=appointment_date)
    assert assign_priority(row, has_valid_phone=True, as_of=AS_OF).band is expected


def test_band_labels_are_stable() -> None:
    """The labels ship in exports. Changing one silently rewrites every diff."""
    assert PriorityBand.A_CHAIN_FOOTHOLD == "A — chain already on panel"
    assert PriorityBand.B_RECENT_RECORD == "B — record added recently"
    assert PriorityBand.C_CONTACTABLE == "C — contactable"
    assert PriorityBand.D_NEEDS_CONTACT == "D — no valid phone number"


# --------------------------------------------------------------------------------------
# Reasons
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("has_valid_phone", [True, False])
@pytest.mark.parametrize("chain_outlets", [0, 2])
@pytest.mark.parametrize("appointment_date", [RECENT_RECORD, OLD_RECORD, None])
def test_every_row_carries_at_least_one_reason(
    has_valid_phone: bool, chain_outlets: int, appointment_date: dt.datetime | None
) -> None:
    """A band with no stated reason would be exactly the opaque score this avoids."""
    row = make_row(chain_on_panel_outlets=chain_outlets, appointment_date=appointment_date)
    priority = assign_priority(row, has_valid_phone=has_valid_phone, as_of=AS_OF)
    assert priority.reasons
    assert all(reason.strip() for reason in priority.reasons)


def test_chain_reason_names_the_count() -> None:
    """Three siblings are reported as three, not as "a chain"."""
    row = make_row(chain_on_panel_outlets=3, name="KLINIK CONTOH TUJUH")
    priority = assign_priority(row, has_valid_phone=True, as_of=AS_OF)
    assert priority.reasons[0] == (
        "3 outlets of this chain are already on the PMCare panel "
        "(inferred from a shared normalised name)"
    )


def test_chain_reason_is_singular_for_one_outlet() -> None:
    """Saying "1 outlets are" would read as a bug and undermine the whole reason."""
    row = make_row(chain_on_panel_outlets=1)
    priority = assign_priority(row, has_valid_phone=True, as_of=AS_OF)
    assert priority.reasons[0] == (
        "1 outlet of this chain is already on the PMCare panel "
        "(inferred from a shared normalised name)"
    )


@pytest.mark.parametrize("chain_outlets", [1, 2, 3, 7, 42])
def test_chain_reason_always_says_inferred(chain_outlets: int) -> None:
    """A shared base name can equally mean the same premises keyed twice.

    The reason must never assert chain membership as fact, at any count.
    """
    row = make_row(chain_on_panel_outlets=chain_outlets)
    priority = assign_priority(row, has_valid_phone=True, as_of=AS_OF)
    chain_reasons = [r for r in priority.reasons if "chain" in r]
    assert chain_reasons, "a chain foothold must produce a reason"
    assert all("inferred" in reason for reason in chain_reasons)


def test_no_chain_reason_without_a_foothold() -> None:
    """Zero on-panel siblings must not produce a chain claim of any kind."""
    row = make_row(chain_on_panel_outlets=0, appointment_date=RECENT_RECORD)
    priority = assign_priority(row, has_valid_phone=True, as_of=AS_OF)
    assert not any("chain" in reason for reason in priority.reasons)


def test_recency_reason_names_the_year_and_whose_record_it_is() -> None:
    """The date is the record's freshness, not the clinic's, and must say so."""
    row = make_row(appointment_date=RECENT_RECORD)
    priority = assign_priority(row, has_valid_phone=True, as_of=AS_OF)
    assert priority.reasons[0] == (
        "record added 2026 — the freshness of PMCare's record, not of the clinic"
    )


def test_contactable_row_states_that_it_has_a_number() -> None:
    """Band C's only reason is the one thing that is true of it."""
    priority = assign_priority(make_row(), has_valid_phone=True, as_of=AS_OF)
    assert priority.band is PriorityBand.C_CONTACTABLE
    assert HAS_PHONE_REASON in priority.reasons


def test_unreachable_row_leads_with_the_missing_number() -> None:
    """The first reason is the work outstanding, phrased as work, not as a demerit."""
    priority = assign_priority(make_row(), has_valid_phone=False, as_of=AS_OF)
    assert priority.reasons[0] == NO_PHONE_REASON
    assert HAS_PHONE_REASON not in priority.reasons


def test_unreachable_row_keeps_its_chain_reason() -> None:
    """A no-phone row with three on-panel siblings is worth chasing a number for.

    Band D is unreachable-today, not worthless, so the other evidence survives.
    """
    row = make_row(chain_on_panel_outlets=3, appointment_date=RECENT_RECORD)
    priority = assign_priority(row, has_valid_phone=False, as_of=AS_OF)
    assert priority.band is PriorityBand.D_NEEDS_CONTACT
    assert any("3 outlets of this chain" in reason for reason in priority.reasons)
    assert any(reason.startswith("record added 2026") for reason in priority.reasons)


# --------------------------------------------------------------------------------------
# Caveats never move a row
# --------------------------------------------------------------------------------------


def test_postcode_state_mismatch_is_a_caveat_not_a_band_change() -> None:
    """Data confidence is surfaced, never ranked."""
    clean = make_row("GRIDGP0001", appointment_date=RECENT_RECORD)
    mismatched = make_row(
        "GRIDGP0002", appointment_date=RECENT_RECORD, postcode_state_mismatch=True
    )

    clean_priority = assign_priority(clean, has_valid_phone=True, as_of=AS_OF)
    mismatch_priority = assign_priority(mismatched, has_valid_phone=True, as_of=AS_OF)

    assert mismatch_priority.band is clean_priority.band
    caveat = "postcode disagrees with the state code — verify the address"
    assert caveat in mismatch_priority.reasons
    assert caveat not in clean_priority.reasons


def test_missing_postcode_is_a_caveat_not_a_band_change() -> None:
    """A row with nothing usable in the postcode column still bands on its own merits."""
    row = make_row(chain_on_panel_outlets=2, postcode=None)
    priority = assign_priority(row, has_valid_phone=True, as_of=AS_OF)
    assert priority.band is PriorityBand.A_CHAIN_FOOTHOLD
    assert "no usable postcode on record — verify the address" in priority.reasons


@pytest.mark.parametrize(
    ("segment", "fragment"),
    [
        (Segment.REVIEW_LIKELY_ON_PANEL, "check before calling"),
        (Segment.REVIEW_FLAGGED, "PNM's own notes flag this record"),
    ],
)
def test_review_segments_surface_a_check_first_caveat(segment: Segment, fragment: str) -> None:
    """A doubtful row can still band high; the caller must be told to look first."""
    row = make_row(
        chain_on_panel_outlets=2,
        segment=segment,
        collides_with_provider_code="GRIDGP9999",
        review_flags=("known_duplicate",),
    )
    priority = assign_priority(row, has_valid_phone=True, as_of=AS_OF)
    assert priority.band is PriorityBand.A_CHAIN_FOOTHOLD
    assert any(fragment in reason for reason in priority.reasons)


def test_stale_record_is_reported_as_a_caveat() -> None:
    """A 2019 record explains a disconnected number before the caller dials it."""
    priority = assign_priority(make_row(), has_valid_phone=True, as_of=AS_OF)
    assert "record last dated 2019 — the details may be out of date" in priority.reasons


def test_undated_record_says_the_vintage_is_unknown() -> None:
    """Silence about a missing date would read as "recent enough"."""
    priority = assign_priority(make_row(appointment_date=None), has_valid_phone=True, as_of=AS_OF)
    assert "no date on PMCare's record — its vintage is unknown" in priority.reasons


# --------------------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------------------


def test_unreachable_rows_sort_last() -> None:
    """Nobody can ring band D today, so it never displaces callable work."""
    rows = [
        make_row("GRIDGP0001", chain_on_panel_outlets=5, appointment_date=RECENT_RECORD),
        make_row("GRIDGP0002", appointment_date=RECENT_RECORD),
        make_row("GRIDGP0003"),
    ]
    phones = {"GRIDGP0001": False, "GRIDGP0002": True, "GRIDGP0003": True}
    ranked = rank(rows, phones, as_of=AS_OF)

    assert codes(ranked) == ("GRIDGP0002", "GRIDGP0003", "GRIDGP0001")
    assert ranked[-1][1].band is PriorityBand.D_NEEDS_CONTACT


def test_a_provider_code_absent_from_the_phone_map_needs_a_contact() -> None:
    """Not knowing of a number and knowing of no number are the same to a caller."""
    rows = [make_row("GRIDGP0001", chain_on_panel_outlets=4)]
    ranked = rank(rows, {}, as_of=AS_OF)
    assert ranked[0][1].band is PriorityBand.D_NEEDS_CONTACT


def test_more_on_panel_siblings_sort_higher_within_band_a() -> None:
    """The warmest relationship is called first."""
    rows = [
        make_row("GRIDGP0001", chain_on_panel_outlets=1),
        make_row("GRIDGP0002", chain_on_panel_outlets=6),
        make_row("GRIDGP0003", chain_on_panel_outlets=3),
    ]
    ranked = rank(rows, all_reachable(rows), as_of=AS_OF)
    assert codes(ranked) == ("GRIDGP0002", "GRIDGP0003", "GRIDGP0001")


def test_more_recent_records_sort_higher_within_a_band() -> None:
    """Undated rows fall to the bottom of their band rather than to the top."""
    rows = [
        make_row("GRIDGP0001", appointment_date=None),
        make_row("GRIDGP0002", appointment_date=OLD_RECORD),
        make_row("GRIDGP0003", appointment_date=dt.datetime(2023, 5, 5)),
    ]
    ranked = rank(rows, all_reachable(rows), as_of=AS_OF)
    assert codes(ranked) == ("GRIDGP0003", "GRIDGP0002", "GRIDGP0001")


def test_territory_breaks_ties_so_one_caller_works_one_area() -> None:
    """State first, then postcode prefix. Never a statement that one state matters more.

    Every row here is otherwise identical, so territory is the only thing left to sort on.
    """
    rows = [
        make_row("GRIDGP0001", state_code="SL", postcode="41000"),
        make_row("GRIDGP0002", state_code="JB", postcode="80000"),
        make_row("GRIDGP0003", state_code="SL", postcode=None),
        make_row("GRIDGP0004", state_code="SL", postcode="40000"),
        make_row("GRIDGP0005", state_code="KL", postcode="50450"),
    ]
    ranked = rank(rows, all_reachable(rows), as_of=AS_OF)
    assert codes(ranked) == (
        "GRIDGP0002",  # JB
        "GRIDGP0005",  # KL
        "GRIDGP0004",  # SL, prefix 40
        "GRIDGP0001",  # SL, prefix 41
        "GRIDGP0003",  # SL, no usable postcode — last within its state
    )


def test_provider_code_breaks_the_final_tie() -> None:
    """With every signal equal, the order is still total and still explainable."""
    rows = [
        make_row("GRIDGP0003"),
        make_row("GRIDGP0001"),
        make_row("GRIDGP0002"),
    ]
    ranked = rank(rows, all_reachable(rows), as_of=AS_OF)
    assert codes(ranked) == ("GRIDGP0001", "GRIDGP0002", "GRIDGP0003")


def test_priority_key_ends_on_the_provider_code() -> None:
    """The determinism guarantee lives in the last element of the key."""
    row = make_row("GRIDGP0042")
    priority = assign_priority(row, has_valid_phone=True, as_of=AS_OF)
    assert priority_key(row, priority)[-1] == "GRIDGP0042"


# --------------------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------------------


def mixed_queue() -> list[QueueBRow]:
    """A queue spanning all four bands, several states and a few data-quality flaws."""
    return [
        make_row("GRIDGP0001", chain_on_panel_outlets=3, appointment_date=RECENT_RECORD),
        make_row("GRIDGP0002", chain_on_panel_outlets=3, state_code="JB"),
        make_row("GRIDGP0003", appointment_date=RECENT_RECORD, postcode_state_mismatch=True),
        make_row("GRIDGP0004", appointment_date=CUTOFF_RECORD, state_code="KL"),
        make_row("GRIDGP0005"),
        make_row("GRIDGP0006", postcode=None, state_code="SR"),
        make_row("GRIDGP0007", chain_on_panel_outlets=1, appointment_date=None),
        make_row("GRIDGP0008", segment=Segment.REVIEW_FLAGGED, review_flags=("closed",)),
    ]


def test_ranking_the_same_input_twice_is_identical() -> None:
    """Month-over-month exports must diff on real change, never on sort instability."""
    rows = mixed_queue()
    phones = {row.provider_code: index % 3 != 0 for index, row in enumerate(rows)}

    first = rank(rows, phones, as_of=AS_OF)
    second = rank(rows, phones, as_of=AS_OF)

    assert [(row.provider_code, p.band, p.reasons) for row, p in first] == [
        (row.provider_code, p.band, p.reasons) for row, p in second
    ]


def test_ranking_does_not_depend_on_input_order() -> None:
    """A total order, not a stable-sort accident of however the rows arrived."""
    rows = mixed_queue()
    phones = {row.provider_code: index % 3 != 0 for index, row in enumerate(rows)}

    forwards = rank(rows, phones, as_of=AS_OF)
    backwards = rank(list(reversed(rows)), phones, as_of=AS_OF)
    rotated = rank(rows[3:] + rows[:3], phones, as_of=AS_OF)

    assert codes(forwards) == codes(backwards) == codes(rotated)


def test_rank_returns_every_row_exactly_once() -> None:
    """Ranking orders a queue; it never filters one."""
    rows = mixed_queue()
    ranked = rank(rows, all_reachable(rows), as_of=AS_OF)
    assert sorted(codes(ranked)) == sorted(row.provider_code for row in rows)


def test_bands_are_contiguous_in_the_ranked_queue() -> None:
    """A to D, in order, with no interleaving — the band is the top-level sort."""
    rows = mixed_queue()
    phones = {row.provider_code: index % 3 != 0 for index, row in enumerate(rows)}
    ranked = rank(rows, phones, as_of=AS_OF)

    order = [PriorityBand.A_CHAIN_FOOTHOLD, PriorityBand.B_RECENT_RECORD]
    order += [PriorityBand.C_CONTACTABLE, PriorityBand.D_NEEDS_CONTACT]
    positions = [order.index(priority.band) for _, priority in ranked]
    assert positions == sorted(positions)
