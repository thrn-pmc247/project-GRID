"""Table-driven cases for address-line and postcode normalisation.

Address fixtures are synthetic; the postcode fixtures are the real *invalid*
values observed in the incumbent master, which are data-quality artefacts rather
than anyone's address (`docs/context/conventions.md`, CLAUDE.md guardrail 5).
"""

from __future__ import annotations

import pytest

from grid.normalise.addresses import (
    AddressParts,
    normalise_postcode,
    parse_address_lines,
    postcode_prefix,
)

#: Real invalid `POSTCODE` values from the incumbent master. Every one must be
#: rejected outright -- see `test_invalid_postcodes_are_rejected_not_repaired`.
INVALID_POSTCODES: list[str] = [
    "814000",  # six digits -- must NOT be truncated to 81400
    "8480",  # four digits -- must NOT be padded to 08480
    "411500",
    "026000",
    "' 8130",  # stray leading quote, and only four digits underneath
    "476301",
    "5000",
    "81750V",  # stray letter
    "7.300",
    "9300",
    "CV5 6J",  # a UK postcode
    f"40000{chr(0xFFFD)}",  # encoding corruption: U+FFFD replacement character
]


@pytest.mark.parametrize("raw", INVALID_POSTCODES)
def test_invalid_postcodes_are_rejected_not_repaired(raw: str) -> None:
    """A NULL with a documented reason beats a plausible guess.

    Truncating `814000` to `81400` or padding `8480` to `08480` would move a
    clinic to another state, so no repair is attempted.
    """
    assert normalise_postcode(raw) == (None, False)


@pytest.mark.parametrize("raw", [None, "", "   ", "\t", "'", "'''"])
def test_blank_postcodes_are_invalid(raw: str | None) -> None:
    assert normalise_postcode(raw) == (None, False)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("43650", "43650"),
        ("50450", "50450"),
        ("05100", "05100"),
        ("00000", "00000"),
        (" 50450 ", "50450"),
        ("'50450", "50450"),
        ("' 50450 ", "50450"),
        ('"81300"', "81300"),
    ],
)
def test_clean_five_digit_postcodes_are_accepted(raw: str, expected: str) -> None:
    assert normalise_postcode(raw) == (expected, True)


@pytest.mark.parametrize(
    ("postcode", "expected"),
    [
        ("43650", "43"),
        ("05100", "05"),
        (" 50450 ", "50"),
        ("'88000", "88"),
        # Invalid input never yields a prefix -- no guessing.
        ("8480", None),
        ("814000", None),
        ("CV5 6J", None),
        ("", None),
        (None, None),
    ],
)
def test_postcode_prefix(postcode: str | None, expected: str | None) -> None:
    """The two-digit prefix is the city-canonicalisation key, nothing more.

    No postcode-to-state mapping is provided here (open question 12).
    """
    assert postcode_prefix(postcode) == expected


# (line1, line2, line3, unit, street, locality)
ADDRESS_CASES: list[
    tuple[str | None, str | None, str | None, str | None, str | None, str | None]
] = [
    (
        "NO. 12, JALAN SS2/24",
        "TAMAN BAHAGIA",
        "47300 PETALING JAYA",
        "NO 12",
        "JALAN SS2/24",
        "TAMAN BAHAGIA",
    ),
    # Abbreviated forms expand in the comparison components.
    (
        "NO 12, JLN SS2/24",
        "TMN BAHAGIA",
        None,
        "NO 12",
        "JALAN SS2/24",
        "TAMAN BAHAGIA",
    ),
    # All three components on one unpunctuated line.
    (
        "LOT 5 JALAN BESAR TAMAN MAJU",
        None,
        None,
        "LOT 5",
        "JALAN BESAR",
        "TAMAN MAJU",
    ),
    # Floor forms are recognised as unit text.
    ("TINGKAT BAWAH, JLN PASAR", "TMN MAJU", None, "TINGKAT BAWAH", "JALAN PASAR", "TAMAN MAJU"),
    (
        "GROUND FLOOR, LRG SEKOLAH",
        None,
        "KG BARU",
        "GROUND FLOOR",
        "LORONG SEKOLAH",
        "KAMPUNG BARU",
    ),
    ("TKT 1, JLN MAJU", None, None, "TINGKAT 1", "JALAN MAJU", None),
    # Shoplot addressing keeps its internal punctuation.
    (
        "BLOK B-3-2, PSN PERDANA",
        "SEKSYEN 9",
        None,
        "BLOK B-3-2",
        "PERSIARAN PERDANA",
        "SEKSYEN 9",
    ),
    ("UNIT 3A", "LBH AMPANG", None, "UNIT 3A", "LEBUH AMPANG", None),
    ("SIMPANG TIGA", None, None, None, "SIMPANG TIGA", None),
    ("LEBUHRAYA SULTANAH", None, None, None, "LEBUHRAYA SULTANAH", None),
    # A postcode-and-city tail still yields the locality.
    (None, None, "43650 BANDAR BARU BANGI", None, None, "BANDAR BARU BANGI"),
    ("PEKAN NANAS", None, None, None, None, "PEKAN NANAS"),
    # A street name that embeds a locality word stays one street.
    ("JALAN KAMPUNG PANDAN", None, None, None, "JALAN KAMPUNG PANDAN", None),
    # Best-effort means unmarked text is simply left unclassified.
    ("KLINIK ALPHA", "WISMA ALPHA", None, None, None, None),
    # Blank and missing lines never raise.
    (None, None, None, None, None, None),
    ("   ", "", None, None, None, None),
    # Lower case input is uppercased in the comparison components.
    ("no. 12, jalan besar", None, None, "NO 12", "JALAN BESAR", None),
]


@pytest.mark.parametrize(
    ("line1", "line2", "line3", "unit", "street", "locality"),
    ADDRESS_CASES,
)
def test_parse_address_lines(
    line1: str | None,
    line2: str | None,
    line3: str | None,
    unit: str | None,
    street: str | None,
    locality: str | None,
) -> None:
    parts = parse_address_lines(line1, line2, line3)
    assert parts.address_unit == unit
    assert parts.address_street == street
    assert parts.address_locality == locality


@pytest.mark.parametrize(
    ("line1", "line2", "line3"),
    [
        ("no. 12, jalan besar", "  Taman Maju  ", None),
        (None, None, None),
        ("   ", "", "\t"),
        ("NO 12", None, "43650 BANDAR BARU BANGI"),
    ],
)
def test_raw_lines_are_always_retained_verbatim(
    line1: str | None,
    line2: str | None,
    line3: str | None,
) -> None:
    """Parsing is best-effort, so the source lines must survive untouched."""
    parts = parse_address_lines(line1, line2, line3)
    assert parts.lines_raw == (line1, line2, line3)


def test_first_match_wins_across_lines() -> None:
    """Where a component appears twice, the first occurrence is kept."""
    parts = parse_address_lines("JALAN SATU", "JALAN DUA", "TAMAN TIGA")
    assert parts.address_street == "JALAN SATU"
    assert parts.address_locality == "TAMAN TIGA"


def test_components_may_span_different_lines() -> None:
    parts = parse_address_lines("LOT 5", "JLN BESAR", "TMN MAJU")
    assert parts == AddressParts(
        address_unit="LOT 5",
        address_street="JALAN BESAR",
        address_locality="TAMAN MAJU",
        lines_raw=("LOT 5", "JLN BESAR", "TMN MAJU"),
    )


def test_section_codes_are_kept_verbatim() -> None:
    """`SS`, `USJ`, `PJU` and `SEKSYEN` are identifiers, not abbreviations."""
    parts = parse_address_lines("JALAN USJ 10/1D", "SEKSYEN 13", None)
    assert parts.address_street == "JALAN USJ 10/1D"
    assert parts.address_locality == "SEKSYEN 13"


def test_address_parts_are_immutable() -> None:
    parts = parse_address_lines("LOT 5", None, None)
    with pytest.raises(AttributeError):
        setattr(parts, "address_unit", "OTHER")  # noqa: B010
