"""Malaysian phone normalisation to +60 E.164 for the phone-first call list.

PNM engages clinics by telephone, so a Queue B row is only actionable if it
carries a number that can actually be dialled. This module turns one free-text
field into a callable E.164 string via `phonenumbers`, and **drops whatever does
not validate**. Nothing is repaired: a number is never padded, truncated, nor
given a guessed missing digit, because a fabricated digit produces a wrong
number that someone will ring.

Two rules go beyond a plain `is_valid_number()` check.

**Region is verified, not assumed.** A `+65` Singapore number validates
perfectly well; without checking `region_code_for_number` it would flow into a
Malaysian call list as though it were a local line. Anything whose number-derived
region is not the requested one is `INVALID`.

**Multi-value fields are split, never trimmed away.** A single field routinely
holds two or three numbers separated by `/`, `,`, `;` or the word `or` -- 42 of
the 4,183 non-blank values in the incumbent extract do. The first value that
validates becomes the primary; every other value is retained verbatim in
`PhoneParts.extra_values`. Choosing one and silently discarding the rest would
lose a working line, and the module has no basis for deciding which number is
"the" clinic line.

For calibration, the same extract yields 3,848 valid numbers from those 4,183
values (321 invalid, 14 unparseable); of the valid ones 3,463 are fixed line and
385 are mobile.

## PDPA

`is_mobile` is the hinge, not a convenience flag. A clinic landline is business
data; a sole proprietor's mobile doubling as the clinic line is **personal data**
(`docs/context/compliance-pdpa.md`, and the `pdpa-review` skill). Callers must
route a mobile-flagged number under the restricted-access rules rather than into
`clinic` or a default API payload. The flag comes from `phonenumbers.number_type`
rather than a leading-digit heuristic on purpose: a `1300`/`1800` hunting line is
a business number whose E.164 form nonetheless opens with a `1`, and a prefix
test would misfile it as somebody's mobile.

Nothing here logs, and nothing here may be made to log -- a phone number is
exactly the payload `docs/context/conventions.md` forbids putting in a log line.

## Editing note

`scripts/check_context.py` check 13 fails the build on a Malaysian mobile-shaped
literal in any tracked file outside `tests/`. Every example below is therefore a
fabricated **fixed line** (`03-2222 3333`). Realistic mobile shapes belong in
`tests/unit/test_normalise_phones.py`, which the check exempts.

Rules: `docs/context/malaysian-data-conventions.md`;
`docs/context/entity-resolution.md` specifies +60 E.164 and drop-invalid.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType
from phonenumbers.phonenumber import PhoneNumber


class PhoneQuality(StrEnum):
    """Verdict of the phone gate for one field."""

    VALID = "VALID"
    """Parsed, valid, and belonging to the requested region. `e164` is populated."""

    INVALID = "INVALID"
    """Parsed but rejected: not a valid number, or valid for another region."""

    UNPARSEABLE = "UNPARSEABLE"
    """`phonenumbers` refused the string outright -- junk, or far too long."""

    MISSING = "MISSING"
    """NULL, blank or whitespace only. Nothing was supplied to assess."""


class LineType(StrEnum):
    """What kind of line a valid number is, as classified by `phonenumbers`."""

    FIXED_LINE = "FIXED_LINE"
    """A landline. Business data: the published clinic line PNM should ring."""

    MOBILE = "MOBILE"
    """A mobile. Potentially personal data under the sole-proprietor rule."""

    OTHER = "OTHER"
    """Valid but neither: toll-free hunting lines, VOIP, premium rate, pagers."""

    UNKNOWN = "UNKNOWN"
    """No type could be established. Also the value for every non-valid verdict."""


DEFAULT_REGION: Final = "MY"
"""ISO 3166-1 alpha-2 region used for parsing and for the region check."""

#: Separators seen between numbers sharing one field. The word `or` is matched on
#: word boundaries so that it cannot bite into a surrounding word.
_FIELD_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[/,;]|\bor\b", re.IGNORECASE)

#: `phonenumbers` number types folded into :class:`LineType`. Only `MOBILE` sets
#: the PDPA flag. `FIXED_LINE_OR_MOBILE` is unreachable for region `MY`, whose
#: metadata keeps the two patterns disjoint; it maps to `OTHER` so that the flag
#: is never set on an ambiguity, and any region change must revisit that choice.
_LINE_TYPES: Final[Mapping[int, LineType]] = MappingProxyType(
    {
        PhoneNumberType.FIXED_LINE: LineType.FIXED_LINE,
        PhoneNumberType.MOBILE: LineType.MOBILE,
        PhoneNumberType.FIXED_LINE_OR_MOBILE: LineType.OTHER,
        PhoneNumberType.TOLL_FREE: LineType.OTHER,
        PhoneNumberType.PREMIUM_RATE: LineType.OTHER,
        PhoneNumberType.SHARED_COST: LineType.OTHER,
        PhoneNumberType.VOIP: LineType.OTHER,
        PhoneNumberType.PERSONAL_NUMBER: LineType.OTHER,
        PhoneNumberType.PAGER: LineType.OTHER,
        PhoneNumberType.UAN: LineType.OTHER,
        PhoneNumberType.VOICEMAIL: LineType.OTHER,
        PhoneNumberType.UNKNOWN: LineType.UNKNOWN,
    }
)

#: Parse failures named for `PhoneParts.note`. The note records why a value was
#: rejected; it never restates the value itself.
_PARSE_ERRORS: Final[Mapping[int, str]] = MappingProxyType(
    {
        NumberParseException.INVALID_COUNTRY_CODE: "INVALID_COUNTRY_CODE",
        NumberParseException.NOT_A_NUMBER: "NOT_A_NUMBER",
        NumberParseException.TOO_SHORT_AFTER_IDD: "TOO_SHORT_AFTER_IDD",
        NumberParseException.TOO_SHORT_NSN: "TOO_SHORT_NSN",
        NumberParseException.TOO_LONG: "TOO_LONG",
    }
)


@dataclass(frozen=True, slots=True)
class PhoneParts:
    """Outcome of normalising one phone field.

    Attributes:
        raw: The input exactly as supplied, always retained -- including for
            `MISSING`, and including any original padding. Never repaired.
        e164: The dialable `+60...` form, or ``None`` for every verdict other
            than `VALID`. An extension is not part of an E.164 number and is
            dropped here; it survives on `national`.
        national: The number formatted for domestic display (`03-2222 3333`), or
            ``None`` unless the verdict is `VALID`.
        quality: Which verdict the gate reached.
        line_type: Line classification for a valid number; `UNKNOWN` otherwise.
        is_mobile: ``True`` only for `LineType.MOBILE`. The PDPA hinge -- see the
            module docstring before storing, exporting or displaying the number.
        extra_values: Every non-primary value found in a multi-value field, in
            source order, each with surrounding whitespace removed and its
            interior untouched. Empty for a single-valued field.
        note: Why a value was rejected, and whether the field was multi-valued.
            ``None`` when a single value validated cleanly. Never contains the
            number.
    """

    raw: str | None
    e164: str | None
    national: str | None
    quality: PhoneQuality
    line_type: LineType
    is_mobile: bool
    extra_values: tuple[str, ...]
    note: str | None


def normalise_phone(raw: str | None, *, region: str = DEFAULT_REGION) -> PhoneParts:
    """Normalise one phone field to E.164, dropping anything that does not validate.

    The field is first split into its constituent values, then each value is
    parsed with `phonenumbers` and checked both for validity and for belonging to
    `region`. The primary value is chosen in this order:

    1. the first value that is `VALID`;
    2. failing that, the first value that at least parsed (`INVALID`), which is
       the more informative verdict to report;
    3. failing that, the first value.

    Every value not chosen is retained verbatim in `extra_values`, so a field
    holding two clinic lines never loses one. No repair is ever attempted: an
    invalid value yields ``e164=None`` rather than a padded or truncated guess.

    Args:
        raw: The source phone field, which may be ``None``, blank or hold several
            numbers.
        region: ISO 3166-1 alpha-2 region, uppercase, used both as the default
            region for parsing and as the region the number must belong to.

    Returns:
        A :class:`PhoneParts`. `e164`, `national` and a meaningful `line_type`
        are populated only when `quality` is `PhoneQuality.VALID`.

    Examples:
        >>> normalise_phone("03-2222 3333").e164
        '+60322223333'
        >>> normalise_phone("03-2222 3333").is_mobile
        False
        >>> parts = normalise_phone("03-2222 3333 / 04-222 3333")
        >>> parts.e164, parts.extra_values
        ('+60322223333', ('04-222 3333',))
        >>> normalise_phone("not a number").quality is PhoneQuality.UNPARSEABLE
        True
    """
    values = split_phone_field(raw)
    if not values:
        return PhoneParts(
            raw=raw,
            e164=None,
            national=None,
            quality=PhoneQuality.MISSING,
            line_type=LineType.UNKNOWN,
            is_mobile=False,
            extra_values=(),
            note=None,
        )

    assessments = [_assess(value, region) for value in values]
    index = _choose_primary(assessments)
    primary = assessments[index]
    extra_values = tuple(value for position, value in enumerate(values) if position != index)
    note = _build_note(primary.reason, len(values), index)

    if primary.quality is not PhoneQuality.VALID or primary.parsed is None:
        return PhoneParts(
            raw=raw,
            e164=None,
            national=None,
            quality=primary.quality,
            line_type=LineType.UNKNOWN,
            is_mobile=False,
            extra_values=extra_values,
            note=note,
        )

    line_type = _LINE_TYPES.get(phonenumbers.number_type(primary.parsed), LineType.OTHER)
    return PhoneParts(
        raw=raw,
        e164=phonenumbers.format_number(primary.parsed, PhoneNumberFormat.E164),
        national=phonenumbers.format_number(primary.parsed, PhoneNumberFormat.NATIONAL),
        quality=PhoneQuality.VALID,
        line_type=line_type,
        is_mobile=line_type is LineType.MOBILE,
        extra_values=extra_values,
        note=note,
    )


def split_phone_field(raw: str | None) -> tuple[str, ...]:
    """Split a field that may hold several numbers into its individual values.

    Splits on `/`, `,`, `;` and the word `or` (any case). Surrounding whitespace
    is removed from each value and empty fragments are dropped; the interior of a
    value is left exactly as supplied, since deciding what its punctuation means
    is `phonenumbers`' job, not this function's.

    Args:
        raw: The source phone field, which may be ``None`` or blank.

    Returns:
        The values in source order. Empty for ``None``, blank or whitespace-only
        input; a single-element tuple for an ordinary field.

    Examples:
        >>> split_phone_field("03-2222 3333 / 04-222 3333")
        ('03-2222 3333', '04-222 3333')
        >>> split_phone_field("03-2222 3333 or 03-2222 3334")
        ('03-2222 3333', '03-2222 3334')
        >>> split_phone_field("   ")
        ()
    """
    if raw is None:
        return ()
    return tuple(
        stripped for fragment in _FIELD_SPLIT_RE.split(raw) if (stripped := fragment.strip())
    )


@dataclass(frozen=True, slots=True)
class _Assessment:
    """One value's verdict, with the parsed number kept only when it is usable.

    Attributes:
        quality: The verdict for this single value; never `MISSING`.
        parsed: The parsed number, present only for `VALID`.
        reason: Why the value was rejected, or ``None`` when it was not.
    """

    quality: PhoneQuality
    parsed: PhoneNumber | None
    reason: str | None


def _assess(value: str, region: str) -> _Assessment:
    """Parse and validate one value, including the region check.

    Args:
        value: A single non-blank value from the field.
        region: The region the number is parsed against and must belong to.

    Returns:
        The value's :class:`_Assessment`.
    """
    try:
        parsed = phonenumbers.parse(value, region)
    except NumberParseException as exc:
        error = _PARSE_ERRORS.get(exc.error_type, "UNRECOGNISED_ERROR")
        return _Assessment(PhoneQuality.UNPARSEABLE, None, f"unparseable ({error})")

    if not phonenumbers.is_valid_number(parsed):
        return _Assessment(PhoneQuality.INVALID, None, f"not a valid number for region {region}")

    number_region = phonenumbers.region_code_for_number(parsed)
    if number_region != region:
        return _Assessment(
            PhoneQuality.INVALID,
            None,
            f"valid for region {number_region or 'unknown'}, not {region}",
        )

    return _Assessment(PhoneQuality.VALID, parsed, None)


def _choose_primary(assessments: Sequence[_Assessment]) -> int:
    """Pick which value of a multi-value field becomes the primary.

    A valid number is preferred over an earlier unusable one because the purpose
    of the field is to yield a line PNM can ring. Nothing is discarded by this
    choice -- the caller retains every other value.

    Args:
        assessments: One assessment per value, in source order; never empty.

    Returns:
        The index of the primary value.
    """
    for position, assessment in enumerate(assessments):
        if assessment.quality is PhoneQuality.VALID:
            return position
    for position, assessment in enumerate(assessments):
        if assessment.quality is PhoneQuality.INVALID:
            return position
    return 0


def _build_note(reason: str | None, value_count: int, index: int) -> str | None:
    """Compose the explanatory note, which must never restate the number.

    Args:
        reason: The primary value's rejection reason, if it was rejected.
        value_count: How many values the field held.
        index: Zero-based position of the primary value.

    Returns:
        The note, or ``None`` when a single value validated cleanly.
    """
    parts: list[str] = []
    if reason is not None:
        parts.append(reason)
    if value_count > 1:
        parts.append(f"field held {value_count} values; primary is value {index + 1}")
    return "; ".join(parts) or None
