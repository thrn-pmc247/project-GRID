"""Table-driven cases for Malaysian phone normalisation.

**Every number here is fabricated.** No value is drawn from the incumbent master
or any other real extract, so nothing in this file is anyone's phone number
(`docs/context/conventions.md`: fixtures are synthetic only; CLAUDE.md guardrail
5). This is also the one place mobile-shaped literals are permitted --
`scripts/check_context.py` check 13 exempts `tests/` and fails the build on such
a literal anywhere else, which is why `src/grid/normalise/phones.py` illustrates
itself with fixed lines only.

The fixed-line shapes were chosen to satisfy the region's own numbering rules:
`03-2222 3333` validates, while `03-1234 5678` does not, because Kuala Lumpur
subscriber numbers may not begin with a `1`. That distinction is itself under
test -- it is exactly the sort of value a padding or truncating "repair" would
manufacture out of nothing.
"""

from __future__ import annotations

import re

import pytest

from grid.normalise.phones import (
    DEFAULT_REGION,
    LineType,
    PhoneParts,
    PhoneQuality,
    normalise_phone,
    split_phone_field,
)

# --------------------------------------------------------------------------
# split_phone_field
# --------------------------------------------------------------------------

# (raw, expected values)
SPLIT_CASES: list[tuple[str | None, tuple[str, ...]]] = [
    (None, ()),
    ("", ()),
    ("   ", ()),
    ("\t\n", ()),
    ("03-2222 3333", ("03-2222 3333",)),
    ("  03-2222 3333  ", ("03-2222 3333",)),
    # Each separator named in the contract.
    ("03-2222 3333 / 04-222 3333", ("03-2222 3333", "04-222 3333")),
    ("03-2222 3333, 04-222 3333", ("03-2222 3333", "04-222 3333")),
    ("03-2222 3333; 04-222 3333", ("03-2222 3333", "04-222 3333")),
    ("03-2222 3333 or 04-222 3333", ("03-2222 3333", "04-222 3333")),
    ("03-2222 3333 OR 04-222 3333", ("03-2222 3333", "04-222 3333")),
    ("012-345 6789 Or 019-876 5432", ("012-345 6789", "019-876 5432")),
    # Three values, mixed separators.
    (
        "03-2222 3333 / 04-222 3333, 012-345 6789",
        ("03-2222 3333", "04-222 3333", "012-345 6789"),
    ),
    # Empty fragments are dropped, never returned as blanks.
    ("03-2222 3333 //", ("03-2222 3333",)),
    (", 03-2222 3333", ("03-2222 3333",)),
    # `or` only splits on word boundaries, so a word merely containing it survives.
    ("Doctor 03-2222 3333", ("Doctor 03-2222 3333",)),
    # A dash is not a separator: it is punctuation inside a single number.
    ("03-2222-3333", ("03-2222-3333",)),
    # Placeholder text splits like anything else; it is not special-cased.
    ("N/A", ("N", "A")),
]


@pytest.mark.parametrize(("raw", "expected"), SPLIT_CASES)
def test_split_phone_field(raw: str | None, expected: tuple[str, ...]) -> None:
    assert split_phone_field(raw) == expected


# --------------------------------------------------------------------------
# Valid numbers
# --------------------------------------------------------------------------

# (raw, expected e164) -- all fixed lines, every common keying shape.
VALID_FIXED_LINE_CASES: list[tuple[str, str]] = [
    ("03-2222 3333", "+60322223333"),
    ("0322223333", "+60322223333"),
    ("+60322223333", "+60322223333"),
    ("60322223333", "+60322223333"),
    ("+60 3 2222 3333", "+60322223333"),
    ("03 2222 3333", "+60322223333"),
    ("(03) 2222 3333", "+60322223333"),
    ("03-2222-3333", "+60322223333"),
    ("03.2222.3333", "+60322223333"),
    ("  03-2222 3333  ", "+60322223333"),
    # An extension is not part of an E.164 number, so it is dropped from `e164`.
    ("03-2222 3333 ext 12", "+60322223333"),
    ("03-2222 3333 x12", "+60322223333"),
    # Regional and East Malaysian ranges.
    ("04-222 3333", "+6042223333"),
    ("05-222 3333", "+6052223333"),
    ("09-222 3333", "+6092223333"),
    ("088-222 333", "+6088222333"),  # Sabah
    ("082-222 333", "+6082222333"),  # Sarawak
]


@pytest.mark.parametrize(("raw", "expected"), VALID_FIXED_LINE_CASES)
def test_valid_fixed_lines(raw: str, expected: str) -> None:
    """A landline is business data: valid, dialable, and not mobile-flagged."""
    parts = normalise_phone(raw)
    assert parts.quality is PhoneQuality.VALID
    assert parts.e164 == expected
    assert parts.line_type is LineType.FIXED_LINE
    assert parts.is_mobile is False
    assert parts.national is not None
    assert parts.extra_values == ()


# (raw, expected e164)
VALID_MOBILE_CASES: list[tuple[str, str]] = [
    ("012-345 6789", "+60123456789"),
    ("0123456789", "+60123456789"),
    ("+60123456789", "+60123456789"),
    ("60123456789", "+60123456789"),
    ("012 345 6789", "+60123456789"),
    ("019-876 5432", "+60198765432"),
    ("010-222 3333", "+60102223333"),
    ("011-2222 3333", "+601122223333"),  # 11-digit mobile range
]


@pytest.mark.parametrize(("raw", "expected"), VALID_MOBILE_CASES)
def test_valid_mobiles_are_flagged(raw: str, expected: str) -> None:
    """`is_mobile` is the PDPA hinge -- a sole proprietor's mobile is personal data."""
    parts = normalise_phone(raw)
    assert parts.quality is PhoneQuality.VALID
    assert parts.e164 == expected
    assert parts.line_type is LineType.MOBILE
    assert parts.is_mobile is True


@pytest.mark.parametrize("raw", ["1300-88-1234", "1-800-88-1234"])
def test_toll_free_lines_are_not_mobiles(raw: str) -> None:
    """A hunting line's E.164 form opens with a `1` but it is not somebody's mobile.

    This is why the flag comes from `phonenumbers.number_type` and not from a
    leading-digit test: a prefix heuristic would misfile a business number as
    personal data, and PDPA handling would follow the wrong branch.
    """
    parts = normalise_phone(raw)
    assert parts.quality is PhoneQuality.VALID
    assert parts.line_type is LineType.OTHER
    assert parts.is_mobile is False


def test_extension_survives_on_national_but_not_e164() -> None:
    parts = normalise_phone("03-2222 3333 ext 12")
    assert parts.e164 == "+60322223333"
    assert parts.national is not None
    assert "12" in parts.national


# --------------------------------------------------------------------------
# Invalid and unparseable
# --------------------------------------------------------------------------

# Values that parse but must be rejected. `phonenumbers` is the authority.
INVALID_CASES: list[str] = [
    "03-222 333",  # too short -- must NOT be padded
    "03-2222 33334",  # too long -- must NOT be truncated
    "0322223",  # far too short
    "03-1234 5678",  # right length, but no KL subscriber number starts with 1
    "015-222 3333",  # unallocated mobile prefix
    "018-999 0000",  # mobile-shaped but not a valid number
    "1234",
    "0000000",
    "03-2222 3333 (Klinik)",  # trailing text corrupts the number
    "6512345678",  # Singapore number keyed without its `+`
]


@pytest.mark.parametrize("raw", INVALID_CASES)
def test_invalid_numbers_are_dropped_never_repaired(raw: str) -> None:
    """Drop invalid: no padding, no truncation, no guessed digit.

    A fabricated digit produces a wrong number that someone will actually ring.
    """
    parts = normalise_phone(raw)
    assert parts.quality is PhoneQuality.INVALID
    assert parts.e164 is None
    assert parts.national is None
    assert parts.line_type is LineType.UNKNOWN
    assert parts.is_mobile is False


UNPARSEABLE_CASES: list[str] = [
    "abc",
    "no phone",
    "TIADA",
    "-",
    "1",
    "031234567890123456789",  # too long for `phonenumbers` to entertain at all
]


@pytest.mark.parametrize("raw", UNPARSEABLE_CASES)
def test_unparseable_values(raw: str) -> None:
    parts = normalise_phone(raw)
    assert parts.quality is PhoneQuality.UNPARSEABLE
    assert parts.e164 is None
    assert parts.line_type is LineType.UNKNOWN


@pytest.mark.parametrize("raw", [None, "", " ", "   ", "\t", "\n", "\t \n"])
def test_missing_values(raw: str | None) -> None:
    parts = normalise_phone(raw)
    assert parts.quality is PhoneQuality.MISSING
    assert parts.e164 is None
    assert parts.national is None
    assert parts.line_type is LineType.UNKNOWN
    assert parts.is_mobile is False
    assert parts.extra_values == ()
    assert parts.note is None


# --------------------------------------------------------------------------
# Region check
# --------------------------------------------------------------------------


def test_valid_singapore_number_is_invalid_for_malaysia() -> None:
    """A `+65` number validates perfectly -- and must never reach a Malaysian call list."""
    parts = normalise_phone("+65 6123 4567")
    assert parts.quality is PhoneQuality.INVALID
    assert parts.e164 is None
    assert parts.note == "valid for region SG, not MY"


def test_same_singapore_number_is_valid_when_singapore_is_asked_for() -> None:
    """The rejection above is about the region mismatch, not about the number."""
    parts = normalise_phone("+65 6123 4567", region="SG")
    assert parts.quality is PhoneQuality.VALID
    assert parts.e164 == "+6561234567"


def test_default_region_is_malaysia() -> None:
    assert DEFAULT_REGION == "MY"


# --------------------------------------------------------------------------
# Multi-value fields
# --------------------------------------------------------------------------

# (raw, expected primary e164, expected extras)
MULTI_VALUE_CASES: list[tuple[str, str, tuple[str, ...]]] = [
    ("03-2222 3333 / 04-222 3333", "+60322223333", ("04-222 3333",)),
    ("03-2222 3333, 04-222 3333", "+60322223333", ("04-222 3333",)),
    ("03-2222 3333; 04-222 3333", "+60322223333", ("04-222 3333",)),
    ("03-2222 3333 or 04-222 3333", "+60322223333", ("04-222 3333",)),
    ("012-345 6789 / 019-876 5432", "+60123456789", ("019-876 5432",)),
    # A partial second number is kept verbatim rather than reconstructed.
    ("03-2222 3333 / 3334", "+60322223333", ("3334",)),
    # Three values: two extras, both retained, in source order.
    (
        "03-2222 3333 / 04-222 3333 / 012-345 6789",
        "+60322223333",
        ("04-222 3333", "012-345 6789"),
    ),
    # The first valid value wins, and the junk ahead of it is still retained.
    ("N/A / 03-2222 3333", "+60322223333", ("N", "A")),
    ("abc, 012-345 6789", "+60123456789", ("abc",)),
    # Interior spacing of an extra is untouched; only its edges are trimmed.
    ("03-2222 3333 /   04 - 222   3333  ", "+60322223333", ("04 - 222   3333",)),
]


@pytest.mark.parametrize(("raw", "expected_e164", "expected_extras"), MULTI_VALUE_CASES)
def test_multi_value_fields_retain_every_other_number(
    raw: str,
    expected_e164: str,
    expected_extras: tuple[str, ...],
) -> None:
    """42 fields in the extract hold more than one number; none may be discarded."""
    parts = normalise_phone(raw)
    assert parts.quality is PhoneQuality.VALID
    assert parts.e164 == expected_e164
    assert parts.extra_values == expected_extras


def test_multi_value_field_notes_how_many_values_it_held() -> None:
    parts = normalise_phone("03-2222 3333 / 04-222 3333")
    assert parts.note == "field held 2 values; primary is value 1"


def test_primary_may_be_a_later_value_when_earlier_ones_do_not_validate() -> None:
    parts = normalise_phone("03-222 333 / 03-2222 3333")
    assert parts.e164 == "+60322223333"
    assert parts.extra_values == ("03-222 333",)
    assert parts.note == "field held 2 values; primary is value 2"


def test_multi_value_field_with_nothing_valid_reports_the_first_parseable_value() -> None:
    """Nothing validates, so the more informative verdict is reported, not a guess."""
    parts = normalise_phone("abc / 03-222 333")
    assert parts.quality is PhoneQuality.INVALID
    assert parts.e164 is None
    assert parts.extra_values == ("abc",)


def test_multi_value_field_with_nothing_parseable_keeps_the_first_value_primary() -> None:
    parts = normalise_phone("N/A")
    assert parts.quality is PhoneQuality.UNPARSEABLE
    assert parts.extra_values == ("A",)
    assert parts.note is not None
    assert parts.note.startswith("unparseable (NOT_A_NUMBER)")


# --------------------------------------------------------------------------
# Invariants
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "03-2222 3333",
        "  03-2222 3333  ",
        "012-345 6789",
        "03-1234 5678",
        "abc",
        "03-2222 3333 / 04-222 3333",
    ],
)
def test_raw_is_always_retained_verbatim(raw: str | None) -> None:
    """Nothing is repaired, so the source value must survive untouched."""
    assert normalise_phone(raw).raw == raw


@pytest.mark.parametrize(
    "raw",
    [
        "03-2222 3333",
        "012-345 6789",
        "03-1234 5678",
        "+65 6123 4567",
        "abc",
        "03-2222 3333 / 04-222 3333",
        "N/A",
    ],
)
def test_note_never_restates_the_number(raw: str) -> None:
    """A note may be logged; a phone number may not (`conventions.md`).

    Notes carry reasons, region codes and small counts only -- never a digit run
    that could reconstruct the value.
    """
    note = normalise_phone(raw).note
    assert note is None or re.search(r"\d{3,}", note) is None


@pytest.mark.parametrize("raw", ["03-1234 5678", "abc", "", "03-222 333"])
def test_nothing_but_valid_yields_a_dialable_number(raw: str) -> None:
    parts = normalise_phone(raw)
    assert parts.quality is not PhoneQuality.VALID
    assert parts.e164 is None
    assert parts.national is None
    assert parts.is_mobile is False


def test_phone_parts_are_immutable() -> None:
    parts = normalise_phone("03-2222 3333")
    with pytest.raises(AttributeError):
        setattr(parts, "e164", "+60322223334")  # noqa: B010


def test_phone_parts_equality_is_by_value() -> None:
    assert normalise_phone("03-2222 3333") == PhoneParts(
        raw="03-2222 3333",
        e164="+60322223333",
        national="03-2222 3333",
        quality=PhoneQuality.VALID,
        line_type=LineType.FIXED_LINE,
        is_mobile=False,
        extra_values=(),
        note=None,
    )
