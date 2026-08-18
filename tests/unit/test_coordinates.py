"""Table-driven tests for the coordinate quality gate.

Fixture policy (docs/context/conventions.md): synthetic values only. The handful of
real coordinate pairs used here are the ones already published in the PR001
reconciliation of out-of-bounds rows — bare numbers carrying no personal data, no
provider identifiers and no address. The parquet is never read from a test.
"""

from __future__ import annotations

import math

import pytest

from grid.normalise.coordinates import (
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
    CoordQuality,
    CoordResult,
    _looks_axis_swapped,
    _repair_concatenation_split,
    _repair_decimal_shift_per_component,
    _repair_decimal_shift_single_power,
    assess_coordinates,
    in_malaysia,
    summarise_qualities,
)

# --------------------------------------------------------------------------------------
# Classification table: (latitude, longitude) -> (quality, clean latitude, clean longitude)
# --------------------------------------------------------------------------------------

_Q = CoordQuality

CASES = [
    # --- VALID: passed through untouched --------------------------------------------
    pytest.param(3.139003, 101.686855, _Q.VALID, 3.139003, 101.686855, id="valid-kl"),
    pytest.param(5.9804, 116.0735, _Q.VALID, 5.9804, 116.0735, id="valid-sabah"),
    pytest.param(1.5533, 110.3592, _Q.VALID, 1.5533, 110.3592, id="valid-sarawak"),
    # Bounds are inclusive — all four corners are VALID.
    pytest.param(LAT_MIN, LON_MIN, _Q.VALID, 0.85, 99.60, id="corner-sw"),
    pytest.param(LAT_MAX, LON_MAX, _Q.VALID, 7.40, 119.30, id="corner-ne"),
    pytest.param(LAT_MIN, LON_MAX, _Q.VALID, 0.85, 119.30, id="corner-se"),
    pytest.param(LAT_MAX, LON_MIN, _Q.VALID, 7.40, 99.60, id="corner-nw"),
    # --- MISSING: nothing to assess --------------------------------------------------
    pytest.param(None, 101.686855, _Q.MISSING, None, None, id="lat-null"),
    pytest.param(3.139003, None, _Q.MISSING, None, None, id="lon-null"),
    pytest.param(None, None, _Q.MISSING, None, None, id="both-null"),
    pytest.param(math.nan, 101.686855, _Q.MISSING, None, None, id="lat-nan"),
    pytest.param(3.139003, math.nan, _Q.MISSING, None, None, id="lon-nan"),
    pytest.param(math.nan, math.nan, _Q.MISSING, None, None, id="both-nan"),
    pytest.param(math.inf, 101.686855, _Q.MISSING, None, None, id="lat-inf"),
    pytest.param(3.139003, -math.inf, _Q.MISSING, None, None, id="lon-neg-inf"),
    pytest.param(-math.inf, math.inf, _Q.MISSING, None, None, id="both-inf"),
    # --- NULL_ISLAND: the imputation bug, never kept as a point ----------------------
    pytest.param(0.0, 0.0, _Q.NULL_ISLAND, None, None, id="null-island"),
    pytest.param(-0.0, 0.0, _Q.NULL_ISLAND, None, None, id="null-island-neg-zero"),
    pytest.param(-0.0, -0.0, _Q.NULL_ISLAND, None, None, id="null-island-both-neg"),
    # A single zero component is NOT Null Island — real row OPT6877.
    pytest.param(0.0, 100.6894069, _Q.OUT_OF_BOUNDS, None, None, id="zero-lat-not-island"),
    pytest.param(3.139003, 0.0, _Q.OUT_OF_BOUNDS, None, None, id="zero-lon-not-island"),
    # --- OUT_OF_BOUNDS: just outside, negative, elsewhere in the world ---------------
    pytest.param(0.8499, 101.686855, _Q.OUT_OF_BOUNDS, None, None, id="just-south"),
    pytest.param(7.4001, 101.686855, _Q.OUT_OF_BOUNDS, None, None, id="just-north"),
    pytest.param(3.139003, 99.5999, _Q.OUT_OF_BOUNDS, None, None, id="just-west"),
    pytest.param(3.139003, 119.3001, _Q.OUT_OF_BOUNDS, None, None, id="just-east"),
    pytest.param(-3.139003, 101.686855, _Q.OUT_OF_BOUNDS, None, None, id="neg-lat"),
    pytest.param(3.139003, -101.686855, _Q.OUT_OF_BOUNDS, None, None, id="neg-lon"),
    pytest.param(-3.139003, -101.686855, _Q.OUT_OF_BOUNDS, None, None, id="neg-both"),
    pytest.param(-6.2, 106.8166, _Q.OUT_OF_BOUNDS, None, None, id="jakarta"),
    # 8.0 sits in the gap between decades of the latitude range: no power lands it.
    pytest.param(8.0, 101.686855, _Q.OUT_OF_BOUNDS, None, None, id="decade-gap"),
    # --- REPAIRED_DECIMAL: exactly one power per component ---------------------------
    # The worked example: real row DEN2559, valid latitude beside an inflated longitude.
    pytest.param(3.112491, 101591143.0, _Q.REPAIRED_DECIMAL, 3.112491, 101.591143, id="den2559"),
    # Largest observed latitude in the master.
    pytest.param(932799.0, 103.8752911, _Q.REPAIRED_DECIMAL, 0.932799, 103.8752911, id="max-lat"),
    # Both components inflated, and here by the same power.
    pytest.param(52540.4, 1003829.4, _Q.REPAIRED_DECIMAL, 5.25404, 100.38294, id="both-inflated"),
    pytest.param(3.164013, 1001.57387, _Q.REPAIRED_DECIMAL, 3.164013, 100.157387, id="lon-x10"),
    # --- Repair abandoned as ambiguous or impossible ---------------------------------
    # Latitude valid, longitude equal to it: no power of ten lifts 3.0638 to >= 99.60.
    pytest.param(3.0638, 3.0638, _Q.OUT_OF_BOUNDS, None, None, id="lat-equals-lon"),
    pytest.param(3.093973, 3.093973, _Q.OUT_OF_BOUNDS, None, None, id="lat-equals-lon-2"),
    # A real point in India: the longitude 77.4977 has no candidate power.
    pytest.param(27.2046, 77.4977, _Q.OUT_OF_BOUNDS, None, None, id="india"),
    # Largest observed longitude, 1.95670001957475e14: no power in 0..12 lands it.
    pytest.param(2.7536752, 195670001957475.0, _Q.OUT_OF_BOUNDS, None, None, id="max-lon"),
    # --- REPAIRED_SPLIT and its abandonment ------------------------------------------
    # Synthetic: latitude 3.5 keyed again in front of longitude 110.35 -> "3511035".
    # The valid latitude prunes every split but one, so the pair is unambiguous.
    pytest.param(3.5, 3511035.0, _Q.REPAIRED_SPLIT, 3.5, 110.35, id="split"),
    # Same digits, but the latitude is unusable so nothing prunes the candidates:
    # "35"/"11035" -> (3.5, 110.35) and "351"/"10350" -> (3.51, 103.5). Ambiguous.
    pytest.param(8.0, 3511035.0, _Q.OUT_OF_BOUNDS, None, None, id="split-ambiguous"),
    # A negative component is never split: the sign is information, not noise.
    pytest.param(-3511035.0, 110.35, _Q.OUT_OF_BOUNDS, None, None, id="split-negative-refused"),
    pytest.param(3.5, -3511035.0, _Q.OUT_OF_BOUNDS, None, None, id="split-negative-lon-refused"),
    # --- Axis-swap guard: abandoned before any repair is attempted -------------------
    # Real rows OPT6002 and OPT6022. In both the raw latitude is itself a valid
    # longitude, so a swapped pair and a decimal error are indistinguishable. The
    # arithmetic would happily divide the latitude by 100 and land inside the box —
    # in the Strait of Malacca and in Singaporean/Indonesian water respectively.
    pytest.param(103.1367898, 101.6633991, _Q.OUT_OF_BOUNDS, None, None, id="swap-opt6002"),
    pytest.param(103.76152, 103.80368, _Q.OUT_OF_BOUNDS, None, None, id="swap-opt6022"),
    # Mirror case: the longitude reads as a latitude. Synthetic, and chosen because
    # without the guard the digits "9327991035" split uniquely into (0.932799, 103.5)
    # and the pair would be REPAIRED_SPLIT — so the mirror guard is not decorative.
    pytest.param(9327991035.0, 3.5, _Q.OUT_OF_BOUNDS, None, None, id="swap-mirror"),
    # --- Documented divergence from the brief's counter-example ----------------------
    # The brief lists (27.2038, 117.6911) as "a real point in China — no power fixes
    # latitude". That is arithmetically untrue: 27.2038 / 10 = 2.72038, which is inside
    # [0.85, 7.40], and 117.6911 is already inside [99.60, 119.30]. It is not a swap
    # either — 27.2038 is not a valid longitude — so the guard does not catch it and
    # the pair repairs. Suppressing it would need an invented rule; reported instead.
    pytest.param(27.2038, 117.6911, _Q.REPAIRED_DECIMAL, 2.72038, 117.6911, id="brief-china"),
    # Real row DEN3105, and the known limitation of a rectangular bounds test: this
    # repairs, lands inside the box, and is in East Kalimantan rather than Sabah.
    # Not a swap (33.9651 is not a valid longitude) and not an arithmetic error.
    # Fixing it needs a Malaysia polygon; recorded as an open question instead.
    pytest.param(33.9651, 117.6911, _Q.REPAIRED_DECIMAL, 3.39651, 117.6911, id="den3105-borneo"),
]


def _assert_clean(actual: float | None, expected: float | None) -> None:
    """Compare one clean component, tolerating float division error."""
    if expected is None:
        assert actual is None
    else:
        assert actual == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize(("lat", "lon", "quality", "clean_lat", "clean_lon"), CASES)
def test_assess_coordinates(
    lat: float | None,
    lon: float | None,
    quality: CoordQuality,
    clean_lat: float | None,
    clean_lon: float | None,
) -> None:
    """Each table row classifies as stated and yields exactly the stated clean pair."""
    result = assess_coordinates(lat, lon)

    assert result.quality is quality
    _assert_clean(result.latitude_clean, clean_lat)
    _assert_clean(result.longitude_clean, clean_lon)


@pytest.mark.parametrize(("lat", "lon", "quality", "clean_lat", "clean_lon"), CASES)
def test_unusable_verdicts_null_both_components(
    lat: float | None,
    lon: float | None,
    quality: CoordQuality,
    clean_lat: float | None,
    clean_lon: float | None,
) -> None:
    """MISSING, NULL_ISLAND and OUT_OF_BOUNDS never leak a half-usable pair."""
    unusable = {CoordQuality.MISSING, CoordQuality.NULL_ISLAND, CoordQuality.OUT_OF_BOUNDS}
    result = assess_coordinates(lat, lon)

    if result.quality in unusable:
        assert result.latitude_clean is None
        assert result.longitude_clean is None
    else:
        assert in_malaysia(result.latitude_clean, result.longitude_clean)


@pytest.mark.parametrize(("lat", "lon", "quality", "clean_lat", "clean_lon"), CASES)
def test_repair_note_present_only_for_repairs(
    lat: float | None,
    lon: float | None,
    quality: CoordQuality,
    clean_lat: float | None,
    clean_lon: float | None,
) -> None:
    """Every repair is auditable; nothing else carries a note."""
    repairs = {CoordQuality.REPAIRED_DECIMAL, CoordQuality.REPAIRED_SPLIT}
    result = assess_coordinates(lat, lon)

    if result.quality in repairs:
        assert result.repair_note
    else:
        assert result.repair_note is None


@pytest.mark.parametrize(("lat", "lon"), [(3.139003, 101.686855), (LAT_MIN, LON_MAX)])
def test_valid_pairs_are_passed_through_bit_for_bit(lat: float, lon: float) -> None:
    """A VALID pair is never rescaled, rounded or otherwise touched."""
    result = assess_coordinates(lat, lon)

    assert result.quality is CoordQuality.VALID
    assert result.latitude_clean == lat
    assert result.longitude_clean == lon


# --------------------------------------------------------------------------------------
# The axis-swap guard
# --------------------------------------------------------------------------------------

SWAP_CASES = [
    pytest.param(103.1367898, 101.6633991, True, id="lat-reads-as-lon-opt6002"),
    pytest.param(103.76152, 103.80368, True, id="lat-reads-as-lon-opt6022"),
    pytest.param(9327991035.0, 3.5, True, id="lon-reads-as-lat-mirror"),
    pytest.param(3.0638, 3.0638, True, id="lon-reads-as-lat-real"),
    pytest.param(LON_MIN, 101.6869, True, id="lat-on-lon-lower-bound"),
    pytest.param(LON_MAX, 101.6869, True, id="lat-on-lon-upper-bound"),
    # Not swaps: the offending component is not valid on the other axis either.
    pytest.param(3.139003, 101.686855, False, id="valid-pair"),
    pytest.param(33.9651, 117.6911, False, id="den3105-not-a-swap"),
    pytest.param(27.2038, 117.6911, False, id="china-not-a-swap"),
    pytest.param(932799.0, 103.8752911, False, id="inflated-lat-not-a-swap"),
    pytest.param(3.112491, 101591143.0, False, id="inflated-lon-not-a-swap"),
    pytest.param(0.0, 100.6894069, False, id="zero-lat-not-a-swap"),
    pytest.param(-103.76152, 103.80368, False, id="negative-lat-not-a-swap"),
]


@pytest.mark.parametrize(("lat", "lon", "expected"), SWAP_CASES)
def test_looks_axis_swapped(lat: float, lon: float, expected: bool) -> None:
    """A component valid on the other axis is swap-ambiguous; nothing else is."""
    assert _looks_axis_swapped(lat, lon) is expected


def test_axis_swap_guard_blocks_a_repair_that_would_otherwise_succeed() -> None:
    """The guard is load-bearing on the latitude side, not merely declarative.

    OPT6002's latitude has exactly one candidate power, so without the guard the
    pair would repair to a point in the Strait of Malacca.
    """
    lat, lon = 103.1367898, 101.6633991

    assert _repair_decimal_shift_per_component(lat, lon) is not None
    assert assess_coordinates(lat, lon).quality is CoordQuality.OUT_OF_BOUNDS


def test_mirror_swap_guard_blocks_a_split_that_would_otherwise_succeed() -> None:
    """The mirror guard is load-bearing too: it blocks an otherwise unique split.

    The digits of 9327991035.0 split uniquely into (0.932799, 103.5), so without
    the guard this pair would be REPAIRED_SPLIT.
    """
    lat, lon = 9327991035.0, 3.5

    assert _repair_concatenation_split(lat, lon) is not None
    assert assess_coordinates(lat, lon).quality is CoordQuality.OUT_OF_BOUNDS


# --------------------------------------------------------------------------------------
# The 30 real out-of-bounds rows of PR001 (the 6,210 Null Island rows are excluded).
# This table is the audit trail for the counts reported to PNM: 14 repair, 16 do not.
# --------------------------------------------------------------------------------------

REAL_OUT_OF_RANGE_ROWS = [
    (3.0638, 3.0638, CoordQuality.OUT_OF_BOUNDS),
    (3.093973, 3.093973, CoordQuality.OUT_OF_BOUNDS),
    (932799.0, 103.8752911, CoordQuality.REPAIRED_DECIMAL),
    (5.22938, 3043248.101, CoordQuality.OUT_OF_BOUNDS),
    (2.72046, 77.4977, CoordQuality.OUT_OF_BOUNDS),
    (3.112491, 101591143.0, CoordQuality.REPAIRED_DECIMAL),
    (4.68136, 2.177658081, CoordQuality.OUT_OF_BOUNDS),
    (27.2046, 77.4977, CoordQuality.OUT_OF_BOUNDS),
    (27.2038, 77.5011, CoordQuality.OUT_OF_BOUNDS),
    (5.174, 1001527.0, CoordQuality.REPAIRED_DECIMAL),
    (3.00451, 11.56132, CoordQuality.OUT_OF_BOUNDS),
    (6.20092, 99.48498, CoordQuality.OUT_OF_BOUNDS),
    (1.28178, 11019502.0, CoordQuality.REPAIRED_DECIMAL),
    (2.24291, 10303986.0, CoordQuality.REPAIRED_DECIMAL),
    (0.0, 100.6894069, CoordQuality.OUT_OF_BOUNDS),
    (1.5592, 10377281.0, CoordQuality.REPAIRED_DECIMAL),
    (3.164013, 1001.57387, CoordQuality.REPAIRED_DECIMAL),
    (103.1367898, 101.6633991, CoordQuality.OUT_OF_BOUNDS),  # OPT6002 — axis swap
    (27.2038, 77.5011, CoordQuality.OUT_OF_BOUNDS),
    (33.9651, 117.6911, CoordQuality.REPAIRED_DECIMAL),
    (3.12114, 10176550.0, CoordQuality.REPAIRED_DECIMAL),
    (1.495977, 3.3858727, CoordQuality.OUT_OF_BOUNDS),
    (52540.4, 1003829.4, CoordQuality.REPAIRED_DECIMAL),
    (2.27503, 1021350.7, CoordQuality.REPAIRED_DECIMAL),
    (2.7536752, 195670001957475.0, CoordQuality.OUT_OF_BOUNDS),
    (5.38896, 200.57109, CoordQuality.OUT_OF_BOUNDS),
    (2.25825, 11.84427, CoordQuality.OUT_OF_BOUNDS),
    (103.76152, 103.80368, CoordQuality.OUT_OF_BOUNDS),  # OPT6022 — axis swap
    (4.45076, 11403784.0, CoordQuality.REPAIRED_DECIMAL),
    (3.210586, 11.7489503, CoordQuality.OUT_OF_BOUNDS),
]


@pytest.mark.parametrize(("lat", "lon", "quality"), REAL_OUT_OF_RANGE_ROWS)
def test_real_out_of_range_rows(lat: float, lon: float, quality: CoordQuality) -> None:
    """Each of the 30 real out-of-range rows keeps the verdict reported to PNM."""
    assert assess_coordinates(lat, lon).quality is quality


def test_real_out_of_range_rows_split_twelve_to_eighteen() -> None:
    """The headline reconciliation: 12 repair by decimal shift, 18 stay unusable.

    Was 14/16 before the axis-swap guard; OPT6002 and OPT6022 now abandon.
    """
    counts = summarise_qualities(
        assess_coordinates(lat, lon) for lat, lon, _ in REAL_OUT_OF_RANGE_ROWS
    )

    assert counts[CoordQuality.REPAIRED_DECIMAL] == 12
    assert counts[CoordQuality.OUT_OF_BOUNDS] == 18
    assert counts[CoordQuality.REPAIRED_SPLIT] == 0
    assert sum(counts.values()) == 30


# --------------------------------------------------------------------------------------
# in_malaysia
# --------------------------------------------------------------------------------------

BOUNDS_CASES = [
    pytest.param(3.139003, 101.686855, True, id="inside"),
    pytest.param(LAT_MIN, LON_MIN, True, id="corner-sw-inclusive"),
    pytest.param(LAT_MAX, LON_MAX, True, id="corner-ne-inclusive"),
    pytest.param(0.8499, 101.686855, False, id="below-lat-min"),
    pytest.param(7.4001, 101.686855, False, id="above-lat-max"),
    pytest.param(3.139003, 99.5999, False, id="below-lon-min"),
    pytest.param(3.139003, 119.3001, False, id="above-lon-max"),
    pytest.param(0.0, 0.0, False, id="null-island"),
    pytest.param(None, 101.686855, False, id="null-lat"),
    pytest.param(3.139003, None, False, id="null-lon"),
    pytest.param(math.nan, 101.686855, False, id="nan-lat"),
    pytest.param(3.139003, math.inf, False, id="inf-lon"),
]


@pytest.mark.parametrize(("lat", "lon", "expected"), BOUNDS_CASES)
def test_in_malaysia(lat: float | None, lon: float | None, expected: bool) -> None:
    """The bounding box is inclusive and rejects every unusable input."""
    assert in_malaysia(lat, lon) is expected


# --------------------------------------------------------------------------------------
# The literal single-power rule, kept for comparison but not wired in
# --------------------------------------------------------------------------------------


def test_single_power_rule_repairs_when_one_shared_power_fits() -> None:
    """One shared power lands both components: the literal rule accepts."""
    repaired = _repair_decimal_shift_single_power(31.12491, 1015.91143)

    assert repaired is not None
    lat, lon, note = repaired
    assert lat == pytest.approx(3.112491, abs=1e-12)
    assert lon == pytest.approx(101.591143, abs=1e-12)
    assert "10^1" in note


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        pytest.param(3.112491, 101591143.0, id="den2559"),
        pytest.param(932799.0, 103.8752911, id="max-lat"),
        pytest.param(5.174, 1001527.0, id="inflated-lon"),
    ],
)
def test_single_power_rule_fails_on_rows_the_wired_in_rule_repairs(lat: float, lon: float) -> None:
    """Why the per-component variant is the one wired in: the literal rule repairs none of these."""
    assert _repair_decimal_shift_single_power(lat, lon) is None
    assert assess_coordinates(lat, lon).quality is CoordQuality.REPAIRED_DECIMAL


# --------------------------------------------------------------------------------------
# summarise_qualities
# --------------------------------------------------------------------------------------


def test_summarise_qualities_zero_fills_every_member() -> None:
    """An empty run still reports all six verdicts, so a caller can reconcile to a total."""
    counts = summarise_qualities([])

    assert set(counts) == set(CoordQuality)
    assert all(count == 0 for count in counts.values())


def test_summarise_qualities_counts_and_zero_fills_absent_members() -> None:
    """Present verdicts are counted; absent ones are still keyed at zero."""
    results = [
        assess_coordinates(3.139003, 101.686855),
        assess_coordinates(5.980400, 116.073500),
        assess_coordinates(0.0, 0.0),
        assess_coordinates(None, None),
        assess_coordinates(27.2046, 77.4977),
        assess_coordinates(3.112491, 101591143.0),
    ]

    counts = summarise_qualities(results)

    assert counts == {
        CoordQuality.VALID: 2,
        CoordQuality.MISSING: 1,
        CoordQuality.NULL_ISLAND: 1,
        CoordQuality.OUT_OF_BOUNDS: 1,
        CoordQuality.REPAIRED_DECIMAL: 1,
        CoordQuality.REPAIRED_SPLIT: 0,
    }
    assert sum(counts.values()) == len(results)


def test_summarise_qualities_accepts_any_iterable() -> None:
    """A generator is consumed exactly once and counted correctly."""
    stream = (CoordResult(None, None, CoordQuality.NULL_ISLAND) for _ in range(6210))

    counts = summarise_qualities(stream)

    assert counts[CoordQuality.NULL_ISLAND] == 6210
    assert sum(counts.values()) == 6210
