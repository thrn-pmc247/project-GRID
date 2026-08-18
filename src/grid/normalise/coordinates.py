"""The coordinate quality gate — classify honestly, repair only the unambiguous.

PR001's coordinates are badly degraded. Measured on the 2026-08-05 extract
(33,643 rows): 17,525 rows have LATITUDE and/or LONGITUDE NULL; of the 16,118
populated pairs only 9,878 are plausibly Malaysian; 6,210 are exactly (0.0, 0.0)
— a single upstream imputation bug accounting for 99.5% of the bad values — and
only 30 are otherwise out of bounds. Maximum observed latitude 932,799.0;
maximum observed longitude 1.95670001957475e14.

Because barely 29% of the master can support a coordinate comparison, a
coordinate is a **confirmatory signal only** in entity resolution — never a
primary matcher. This module exists to say which of the two a given row is.

Guardrail: never silently coerce. No clamping, no truncation, no "close
enough". Anything ambiguous stays `OUT_OF_BOUNDS` with both clean values None —
a NULL with a documented reason beats a plausible guess. Every repair records a
`repair_note` naming the rule that fired and exactly what it did, so an auditor
can reconstruct the decision without re-running the code.

Repair rules, applied in order and only after the plain checks fail:

**(a) Decimal shift.** Two readings of this rule exist and both are implemented.

* `_repair_decimal_shift_single_power` is the *literal* reading: one shared
  power of ten divides both components and must land both in range. It is
  exposed for testing and comparison but is **not** wired into
  `assess_coordinates`, because on this data it repairs essentially nothing —
  the characteristic broken row carries one valid component and one inflated
  one (real row DEN2559 is latitude 3.112491, longitude 101591143.0), and any
  shared power that rescues the longitude destroys the latitude.
* `_repair_decimal_shift_per_component` is the *conservative per-component*
  reading, and is the one wired in. Each component is scaled independently and
  a component contributes a repair only when exactly one power in 0..12 lands
  it inside its own axis range. Zero candidate powers, or more than one, means
  the value is ambiguous and repair (a) is abandoned wholesale.

  This is an approved, documented deviation from the brief's literal wording.
  Note that with the current bounds "exactly one" can only ever mean "at most
  one": both axis ranges span less than a factor of ten, so two powers can
  never both land. The uniqueness test is kept anyway — it is what makes the
  rule safe if the bounds are ever widened.

**Axis-swap guard, applied before either repair.** A raw latitude that is
itself a valid *longitude* is the signature of a swapped pair, not of a decimal
error — and swap-versus-shift is precisely the kind of ambiguity that must
abandon the repair rather than pick a winner. Real rows OPT6002
(103.1367898, 101.6633991) and OPT6022 (103.76152, 103.80368) both look like
clean decimal repairs to the arithmetic — divide the latitude by 100 and it
lands in the box — but the results sit in the Strait of Malacca and in
Singaporean/Indonesian water respectively. Both are therefore refused and left
`OUT_OF_BOUNDS`.

The mirror case (a raw longitude outside its own range but inside the latitude
range) is treated identically. The two are symmetric in principle, and while
the mirror can never block a decimal repair in practice — this module only ever
divides, and dividing can never lift a value from the latitude range up into
the longitude range — it can and does block a *split* repair, so it earns its
place rather than being merely decorative. The two ranges are disjoint, so
neither guard can fire on a genuinely good pair.

**(b) Concatenation split.** A single value that looks like a latitude's digits
run straight into a longitude's. The value's digit string is split at every
position, each half is scaled by the same unique-power test as (a), and the
split is accepted only if exactly one distinct in-range pair comes out of it.
Where the *other* component is already in range it acts as a consistency check:
the corresponding half must agree with it, and the already-valid component is
kept in preference to the reconstructed one. On the current extract this rule
legitimately fires zero times; it is not tuned to force a hit.

**Known limitation — the bounds are a rectangle, not Malaysia.** The box spans
Peninsular Malaysia through Sabah and Sarawak, and in doing so it necessarily
also contains Sumatra, most of Kalimantan, southern Thailand, Singapore, Brunei
and a great deal of open sea. A point inside it is *plausibly* Malaysian and
nothing stronger; it is never verified. Real row DEN3105 (33.9651, 117.6911)
demonstrates the cost: the latitude has exactly one candidate power, the result
(3.39651, 117.6911) falls inside the box, and the rule therefore repairs it —
but that point is in East Kalimantan, not Sabah. It is not a swap (33.9651 is
not a valid longitude) and it is not an arithmetic error; it is the rectangle
being coarse. Distinguishing it needs a Malaysia polygon, which this project
does not have. It is recorded as an open question. Until it is settled, do not
read `VALID` or either repaired verdict as proof that a point is in Malaysia.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final


class CoordQuality(StrEnum):
    """Verdict of the coordinate gate for one row."""

    VALID = "VALID"
    """Both components were supplied and already inside the Malaysian bounding box."""

    MISSING = "MISSING"
    """At least one component was NULL, NaN or infinite. Nothing to assess."""

    NULL_ISLAND = "NULL_ISLAND"
    """Exactly (0.0, 0.0) — the upstream imputation bug, not a location."""

    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
    """Outside the bounding box and not unambiguously repairable. Clean values are None."""

    REPAIRED_DECIMAL = "REPAIRED_DECIMAL"
    """Recovered by a unique decimal shift. See `CoordResult.repair_note`."""

    REPAIRED_SPLIT = "REPAIRED_SPLIT"
    """Recovered by splitting one concatenated value. See `CoordResult.repair_note`."""


LAT_MIN: Final = 0.85
LAT_MAX: Final = 7.40
LON_MIN: Final = 99.60
LON_MAX: Final = 119.30

MAX_DECIMAL_SHIFT: Final = 12
"""Highest power of ten tried when rescaling a component (inclusive)."""

_CONSISTENCY_ABS_TOL: Final = 1e-6
"""~11 cm. How closely a split-derived half must agree with an already-valid component."""

_DIGITS: Final = "0123456789"


@dataclass(frozen=True, slots=True)
class CoordResult:
    """Outcome of assessing one coordinate pair.

    Attributes:
        latitude_clean: Usable latitude, or None whenever the pair is not usable.
        longitude_clean: Usable longitude, or None whenever the pair is not usable.
        quality: Which verdict the gate reached.
        repair_note: For repaired pairs, exactly which rule fired and what it did.
            None for every unrepaired verdict.
    """

    latitude_clean: float | None
    longitude_clean: float | None
    quality: CoordQuality
    repair_note: str | None = None


def in_malaysia(lat: float | None, lon: float | None) -> bool:
    """Whether a pair sits inside the Malaysian bounding box.

    Args:
        lat: Latitude in decimal degrees, or None.
        lon: Longitude in decimal degrees, or None.

    Returns:
        True only when both components are supplied, finite and within the
        inclusive bounds. NULL, NaN and infinity are all False.
    """
    if lat is None or lon is None or not (math.isfinite(lat) and math.isfinite(lon)):
        return False
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX


def assess_coordinates(lat: float | None, lon: float | None) -> CoordResult:
    """Classify a coordinate pair and repair it only where the repair is unambiguous.

    The order of checks is fixed:

    1. Either component NULL, NaN or infinite -> `MISSING`.
    2. Both exactly 0.0 -> `NULL_ISLAND`. (0.0, 0.0) is never kept as a point;
       a single zero component alongside a valid one is *not* Null Island.
    3. Both already in bounds -> `VALID`, values passed through untouched.
    4. Either component reads as the other axis -> `OUT_OF_BOUNDS`. A swapped
       pair cannot be told from a decimal error, so no repair is attempted.
    5. Decimal shift, then concatenation split. First rule that succeeds wins.
    6. Anything else -> `OUT_OF_BOUNDS`, both clean values None.

    Args:
        lat: Latitude as keyed by the source, or None.
        lon: Longitude as keyed by the source, or None.

    Returns:
        A `CoordResult`. Clean values are non-None only for `VALID`,
        `REPAIRED_DECIMAL` and `REPAIRED_SPLIT`.
    """
    if lat is None or lon is None or not (math.isfinite(lat) and math.isfinite(lon)):
        return CoordResult(None, None, CoordQuality.MISSING)

    if lat == 0.0 and lon == 0.0:
        return CoordResult(None, None, CoordQuality.NULL_ISLAND)

    if in_malaysia(lat, lon):
        return CoordResult(lat, lon, CoordQuality.VALID)

    if _looks_axis_swapped(lat, lon):
        return CoordResult(None, None, CoordQuality.OUT_OF_BOUNDS)

    shifted = _repair_decimal_shift_per_component(lat, lon)
    if shifted is not None:
        clean_lat, clean_lon, note = shifted
        return CoordResult(clean_lat, clean_lon, CoordQuality.REPAIRED_DECIMAL, note)

    split = _repair_concatenation_split(lat, lon)
    if split is not None:
        clean_lat, clean_lon, note = split
        return CoordResult(clean_lat, clean_lon, CoordQuality.REPAIRED_SPLIT, note)

    return CoordResult(None, None, CoordQuality.OUT_OF_BOUNDS)


def summarise_qualities(results: Iterable[CoordResult]) -> dict[CoordQuality, int]:
    """Count results per verdict, with every verdict present.

    Zero-filled so a caller can reconcile the counts to a known row total without
    having to guard for absent keys.

    Args:
        results: Any iterable of assessed results.

    Returns:
        A count for every `CoordQuality` member, in declaration order.
    """
    counts: dict[CoordQuality, int] = dict.fromkeys(CoordQuality, 0)
    for result in results:
        counts[result.quality] += 1
    return counts


def _looks_axis_swapped(lat: float, lon: float) -> bool:
    """Whether either component reads as a valid value for the *other* axis.

    A latitude of 103.76152 is not a plausible latitude but is a perfectly
    plausible longitude, so the row is ambiguous between a swapped pair and a
    decimal error. There is no evidence in the row itself to choose between
    them, and the two readings put the clinic in different countries, so the
    only honest answer is to repair nothing. The mirror case is treated the
    same way for symmetry; see the module docstring for why it is not merely
    decorative.

    The latitude and longitude ranges are disjoint, so this can never fire on a
    pair that is already `VALID`.

    Args:
        lat: Raw latitude, finite.
        lon: Raw longitude, finite.

    Returns:
        True when repair must be abandoned as swap-ambiguous.
    """
    lat_reads_as_longitude = not (LAT_MIN <= lat <= LAT_MAX) and LON_MIN <= lat <= LON_MAX
    lon_reads_as_latitude = not (LON_MIN <= lon <= LON_MAX) and LAT_MIN <= lon <= LAT_MAX
    return lat_reads_as_longitude or lon_reads_as_latitude


def _candidate_powers(value: float, low: float, high: float) -> list[int]:
    """Powers of ten that divide `value` into the inclusive range [low, high].

    Args:
        value: The raw component.
        low: Inclusive lower bound of the component's axis.
        high: Inclusive upper bound of the component's axis.

    Returns:
        Every p in 0..`MAX_DECIMAL_SHIFT` for which `value / 10**p` lands in range.
        More than one entry means the rescale is ambiguous; none means it is
        impossible.
    """
    return [p for p in range(MAX_DECIMAL_SHIFT + 1) if low <= value / 10**p <= high]


def _unique_power(value: float, low: float, high: float) -> int | None:
    """The single power of ten that rescales `value` into range, if there is exactly one."""
    powers = _candidate_powers(value, low, high)
    return powers[0] if len(powers) == 1 else None


def _repair_decimal_shift_per_component(lat: float, lon: float) -> tuple[float, float, str] | None:
    """Rescale each component independently by its own unique power of ten.

    The wired-in reading of repair (a). Each component must have exactly one
    candidate power for its own axis — a component already in range takes p=0 —
    and the resulting pair must be in bounds. Anything else abandons the repair.

    Args:
        lat: Raw latitude, finite.
        lon: Raw longitude, finite.

    Returns:
        `(latitude, longitude, repair_note)`, or None when the shift is
        ambiguous or impossible.
    """
    lat_power = _unique_power(lat, LAT_MIN, LAT_MAX)
    lon_power = _unique_power(lon, LON_MIN, LON_MAX)
    if lat_power is None or lon_power is None:
        return None

    clean_lat = lat / 10**lat_power
    clean_lon = lon / 10**lon_power
    if not in_malaysia(clean_lat, clean_lon):
        return None

    note = f"decimal shift (per-component): latitude /10^{lat_power}, longitude /10^{lon_power}"
    return clean_lat, clean_lon, note


def _repair_decimal_shift_single_power(lat: float, lon: float) -> tuple[float, float, str] | None:
    """Rescale both components by one shared power of ten — the literal reading.

    Kept for comparison and testing only; `assess_coordinates` does not call it.
    It repairs essentially nothing on PR001, because the typical broken row has
    one valid component that any longitude-rescuing power would destroy. See the
    module docstring.

    Args:
        lat: Raw latitude, finite.
        lon: Raw longitude, finite.

    Returns:
        `(latitude, longitude, repair_note)` when exactly one shared power lands
        both components in range, else None.
    """
    powers = [p for p in range(MAX_DECIMAL_SHIFT + 1) if in_malaysia(lat / 10**p, lon / 10**p)]
    if len(powers) != 1:
        return None

    power = powers[0]
    note = f"decimal shift (single power): both components /10^{power}"
    return lat / 10**power, lon / 10**power, note


def _digit_string(value: float) -> str:
    """The decimal digits of `value`, dropping sign, point, exponent and trailing zeros.

    Uses `Decimal` so that very large magnitudes (the longitude column reaches
    1.95670001957475e14) are written out in full rather than in exponent form.
    Callers must not pass a negative value — see `_repair_concatenation_split`.
    """
    text = format(Decimal(str(value)).normalize(), "f")
    return "".join(ch for ch in text if ch in _DIGITS)


def _agrees(candidate: float, existing: float) -> bool:
    """Whether a split-derived half matches a component that is already in range."""
    return math.isclose(candidate, existing, rel_tol=1e-9, abs_tol=_CONSISTENCY_ABS_TOL)


def _split_candidates(
    value: float, source: str, other_lat: float | None, other_lon: float | None
) -> dict[tuple[float, float], str]:
    """Every in-range pair recoverable by splitting one value's digit string.

    The digit string is cut at each interior position, the left half is read as a
    latitude and the right half as a longitude, and each half is scaled by the
    same unique-power test used by repair (a). Where the caller passes an
    already-valid counterpart it must agree with the corresponding half, and the
    already-valid value is the one kept.

    Args:
        value: The suspect component being split.
        source: "latitude" or "longitude" — names the split value in the note.
        other_lat: The row's latitude if it is already in range, else None.
        other_lon: The row's longitude if it is already in range, else None.

    Returns:
        A mapping of distinct resulting pairs to the note for the first split
        position that produced each. More than one entry means ambiguity.
    """
    digits = _digit_string(value)
    candidates: dict[tuple[float, float], str] = {}

    for cut in range(1, len(digits)):
        left, right = digits[:cut], digits[cut:]
        lat_power = _unique_power(float(int(left)), LAT_MIN, LAT_MAX)
        lon_power = _unique_power(float(int(right)), LON_MIN, LON_MAX)
        if lat_power is None or lon_power is None:
            continue

        clean_lat = int(left) / 10**lat_power
        clean_lon = int(right) / 10**lon_power
        if other_lat is not None:
            if not _agrees(clean_lat, other_lat):
                continue
            clean_lat = other_lat
        if other_lon is not None:
            if not _agrees(clean_lon, other_lon):
                continue
            clean_lon = other_lon
        if not in_malaysia(clean_lat, clean_lon):
            continue

        note = (
            f"concatenation split: {source} digits {digits!r} cut at {cut} into "
            f"{left!r}/10^{lat_power} and {right!r}/10^{lon_power}"
        )
        candidates.setdefault((clean_lat, clean_lon), note)

    return candidates


def _repair_concatenation_split(lat: float, lon: float) -> tuple[float, float, str] | None:
    """Recover a pair from a value that is two coordinates run together.

    Only a component that is itself out of its axis range is treated as suspect —
    a component already in range is evidence, not a candidate for surgery. All
    candidates from both components are pooled and the repair is accepted only
    when they agree on exactly one pair.

    Negative components are never split. Splitting works on a digit string and so
    would silently discard the sign, and a minus sign is real information: the
    whole of Malaysia is north of the equator and east of Greenwich, so a negative
    value is a signal about the row, not noise to be dropped.

    Args:
        lat: Raw latitude, finite.
        lon: Raw longitude, finite.

    Returns:
        `(latitude, longitude, repair_note)`, or None when there is no candidate
        or more than one.
    """
    lat_ok = LAT_MIN <= lat <= LAT_MAX
    lon_ok = LON_MIN <= lon <= LON_MAX

    candidates: dict[tuple[float, float], str] = {}
    if not lat_ok and lat > 0:
        candidates.update(_split_candidates(lat, "latitude", None, lon if lon_ok else None))
    if not lon_ok and lon > 0:
        for pair, note in _split_candidates(
            lon, "longitude", lat if lat_ok else None, None
        ).items():
            candidates.setdefault(pair, note)

    if len(candidates) != 1:
        return None

    (clean_lat, clean_lon), note = next(iter(candidates.items()))
    return clean_lat, clean_lon, note
