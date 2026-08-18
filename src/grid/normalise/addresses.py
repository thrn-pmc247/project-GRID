"""Address-line and postcode normalisation for the incumbent provider master.

Addresses arrive as three free-text lines (`ADDRESS1`, `ADDRESS2`, `ADDRESS3`)
with no agreed structure: the unit, street and locality land on whichever line
the keying clerk chose. Parsing is therefore explicitly **best-effort** and the
three raw lines are **always retained verbatim** on :class:`AddressParts` -- the
parsed components are a comparison aid, never a replacement for the source.

Postcodes are treated the same way. `normalise_postcode` accepts only exactly
five digits after whitespace and stray leading quotes are removed; it never
repairs a value. `814000` is not silently truncated to `81400` and `8480` is not
padded to `08480`, because either guess would place a clinic in the wrong state.
A NULL with a documented reason beats a plausible guess.

Out of scope here by decision: any postcode-to-state mapping. Open question 12
records that the authoritative Pos Malaysia-derived dataset is unresolved, and
the folkloric prefix ranges must not be coded. :func:`postcode_prefix` exposes
the two-digit key and stops there.

Rules: `docs/context/malaysian-data-conventions.md` and the
`malaysian-address-normalisation` skill.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

#: Whole-token street and locality abbreviations expanded in the parsed
#: components. The raw lines keep the original spelling. Section codes (`SS`,
#: `PJU`, `USJ`, `SEK`) are deliberately absent -- the skill file keeps them
#: verbatim because they are identifiers, not abbreviations.
#: `LBH` expands to `LEBUH` per the skill file; `grid.normalise.names` expands the
#: same token to `LEBOH` inside branch qualifiers, matching the spelling used
#: there in the incumbent master. Both spellings occur in Malaysian addressing.
STREET_ABBREVIATIONS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "JLN": "JALAN",
        "LRG": "LORONG",
        "PSN": "PERSIARAN",
        "LBH": "LEBUH",
        "TMN": "TAMAN",
        "KG": "KAMPUNG",
        "KPG": "KAMPUNG",
        "BDR": "BANDAR",
        "BT": "BATU",
        "SG": "SUNGAI",
        "TKT": "TINGKAT",
    }
)

_UNIT_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "NO",
        "NOS",
        "LOT",
        "PT",
        "UNIT",
        "BLOK",
        "BLOCK",
        "TINGKAT",
        "TKT",
        "ARAS",
        "GF",
        "G/F",
        "1/F",
    }
)

#: Multi-token unit prefixes. `TINGKAT BAWAH`, `GROUND FLOOR` and `G/F` are the
#: same floor; canonicalising between them is the matcher's job, not this
#: module's -- here they only need to be recognised as unit text.
_UNIT_PHRASES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("GROUND", "FLOOR"),
        ("FIRST", "FLOOR"),
        ("SECOND", "FLOOR"),
        ("1ST", "FLOOR"),
        ("2ND", "FLOOR"),
    }
)

_STREET_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "JALAN",
        "JLN",
        "LORONG",
        "LRG",
        "PERSIARAN",
        "PSN",
        "LEBUH",
        "LBH",
        "LEBUHRAYA",
        "SIMPANG",
    }
)

_LOCALITY_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "TAMAN",
        "TMN",
        "BANDAR",
        "BDR",
        "KAMPUNG",
        "KG",
        "KPG",
        "SEKSYEN",
        "PEKAN",
    }
)

_SEGMENT_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[,;]+")
_POSTCODE_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9]{5}$")
#: Stray quoting picked up from spreadsheet exports, e.g. `' 8130`. The curly
#: quotes are built from code points so the source itself stays ASCII.
_CURLY_QUOTE_CODES: Final[tuple[int, ...]] = (0x2018, 0x2019, 0x201C, 0x201D)
_QUOTE_CHARS: Final[str] = "'\"`" + "".join(chr(code) for code in _CURLY_QUOTE_CODES)
#: Punctuation trimmed from the ends of a token; internal punctuation is kept so
#: that `SS2/24`, `B-3-2` and `G/F` survive intact.
_EDGE_PUNCTUATION: Final[str] = ".,;:()"

#: A chunk that already begins with a marker only yields to a following marker
#: once it holds this many tokens, which keeps street names that embed a locality
#: word intact (`JALAN KAMPUNG PANDAN` stays one street rather than splitting at
#: `KAMPUNG`). Unmarked leading text (`43650 BANDAR BARU BANGI`) always yields.
_MIN_CHUNK_TOKENS: Final[int] = 2


@dataclass(frozen=True, slots=True)
class AddressParts:
    """Best-effort address components alongside the verbatim source lines.

    Attributes:
        address_unit: Unit, lot or floor text (uppercased), or ``None``.
        address_street: Street text with abbreviations expanded, or ``None``.
        address_locality: Locality text with abbreviations expanded, or ``None``.
        lines_raw: The three input lines exactly as supplied, including ``None``
            and any original casing or padding. Never discarded.
    """

    address_unit: str | None
    address_street: str | None
    address_locality: str | None
    lines_raw: tuple[str | None, str | None, str | None]


def parse_address_lines(
    line1: str | None,
    line2: str | None,
    line3: str | None,
) -> AddressParts:
    """Classify three free-text address lines into unit, street and locality.

    Each line is split on commas and semicolons, then on street and locality
    marker tokens, and each resulting chunk is classified by its leading marker.
    The first chunk found for a component wins; unmarked text (a clinic name, a
    postcode-and-city tail) is simply left unclassified. Nothing is inferred: a
    line with no recognised marker yields ``None`` components, and the raw lines
    remain available on the result.

    Args:
        line1: `ADDRESS1`, which may be ``None`` or blank.
        line2: `ADDRESS2`, which may be ``None`` or blank.
        line3: `ADDRESS3`, which may be ``None`` or blank.

    Returns:
        The parsed :class:`AddressParts`, always carrying ``lines_raw``.

    Examples:
        >>> parts = parse_address_lines("NO. 12, JLN SS2/24", "TMN BAHAGIA", None)
        >>> parts.address_unit, parts.address_street, parts.address_locality
        ('NO 12', 'JALAN SS2/24', 'TAMAN BAHAGIA')
    """
    lines_raw: tuple[str | None, str | None, str | None] = (line1, line2, line3)

    unit: str | None = None
    street: str | None = None
    locality: str | None = None

    for line in lines_raw:
        if line is None or not line.strip():
            continue
        for segment in _SEGMENT_SPLIT_RE.split(line.upper()):
            tokens = segment.split()
            if not tokens:
                continue
            for chunk in _split_chunks(tokens):
                kind = _classify(chunk)
                if kind == "street" and street is None:
                    street = _finalise(chunk)
                elif kind == "locality" and locality is None:
                    locality = _finalise(chunk)
                elif kind == "unit" and unit is None:
                    unit = _finalise(chunk)

    return AddressParts(
        address_unit=unit,
        address_street=street,
        address_locality=locality,
        lines_raw=lines_raw,
    )


def normalise_postcode(raw: str | None) -> tuple[str | None, bool]:
    """Validate a postcode without ever repairing it.

    Surrounding whitespace and stray quote characters left by spreadsheet exports
    (`' 8130`) are removed. Whatever remains must be exactly five ASCII digits.
    Six-digit values (`814000`), short values (`8480`, `5000`), values carrying a
    stray letter (`81750V`), a foreign postcode (`CV5 6J`) and encoding
    corruption (`40000` followed by U+FFFD) are all rejected outright rather than
    truncated, padded or cleaned -- a wrong postcode silently relocates a clinic.

    Args:
        raw: The `POSTCODE` value, which may be ``None`` or blank.

    Returns:
        A ``(postcode, is_valid)`` pair: the five-digit string and ``True`` when
        the value is clean, otherwise ``(None, False)``.

    Examples:
        >>> normalise_postcode("' 50450 ")
        ('50450', True)
        >>> normalise_postcode("814000")
        (None, False)
    """
    if raw is None:
        return None, False
    candidate = raw.strip().strip(_QUOTE_CHARS).strip()
    if _POSTCODE_RE.match(candidate) is None:
        return None, False
    return candidate, True


def postcode_prefix(postcode: str | None) -> str | None:
    """Return the two-digit postcode prefix used as a city-canonicalisation key.

    The prefix is a grouping key only. This module deliberately ships **no**
    postcode-to-state table: open question 12 records that the authoritative
    Pos Malaysia-derived dataset is unresolved, and the well-known prefix ranges
    are folklore that must not be coded. Any state mapping is derived
    empirically elsewhere.

    Args:
        postcode: A postcode, normalised or raw; invalid values yield ``None``.

    Returns:
        The first two digits, or ``None`` when the postcode is not valid.

    Examples:
        >>> postcode_prefix("43650")
        '43'
        >>> postcode_prefix("8480") is None
        True
    """
    normalised, is_valid = normalise_postcode(postcode)
    if not is_valid or normalised is None:
        return None
    return normalised[:2]


def _split_chunks(tokens: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    """Split a token run at street and locality markers.

    A chunk that is itself headed by a marker holds on to a following marker
    until it has at least :data:`_MIN_CHUNK_TOKENS` tokens, so a street name that
    embeds a locality word (`JALAN KAMPUNG PANDAN`) is not torn in half.

    Args:
        tokens: Whitespace-split tokens of one comma-delimited segment.

    Returns:
        The chunks, in order.
    """
    chunks: list[tuple[str, ...]] = []
    current: list[str] = []
    for token in tokens:
        key = _marker_key(token)
        starts_component = key in _STREET_MARKERS or key in _LOCALITY_MARKERS
        head_is_marker = bool(current) and _classify(current) in {"street", "locality"}
        may_split = len(current) >= _MIN_CHUNK_TOKENS or not head_is_marker
        if starts_component and current and may_split:
            chunks.append(tuple(current))
            current = []
        current.append(token)
    if current:
        chunks.append(tuple(current))
    return tuple(chunks)


def _classify(chunk: Sequence[str]) -> str | None:
    """Classify one chunk by its leading marker.

    Args:
        chunk: Tokens of a single chunk.

    Returns:
        ``"street"``, ``"locality"``, ``"unit"``, or ``None`` when the chunk
        carries no recognised marker.
    """
    if not chunk:
        return None
    head = _marker_key(chunk[0])
    if head in _STREET_MARKERS:
        return "street"
    if head in _LOCALITY_MARKERS:
        return "locality"
    if head in _UNIT_MARKERS:
        return "unit"
    if len(chunk) >= 2 and (head, _marker_key(chunk[1])) in _UNIT_PHRASES:
        return "unit"
    return None


def _finalise(chunk: Sequence[str]) -> str | None:
    """Render a chunk as a comparison string with abbreviations expanded.

    Args:
        chunk: Tokens of a single chunk.

    Returns:
        The rendered component, or ``None`` if nothing survives trimming.
    """
    tokens = [
        STREET_ABBREVIATIONS.get(trimmed, trimmed)
        for token in chunk
        if (trimmed := token.strip(_EDGE_PUNCTUATION))
    ]
    rendered = " ".join(tokens)
    return rendered or None


def _marker_key(token: str) -> str:
    """Reduce a token to its marker-lookup form.

    Args:
        token: A single uppercased token, possibly punctuated (`NO.`, `JALAN,`).

    Returns:
        The token without edge punctuation.
    """
    return token.strip(_EDGE_PUNCTUATION)
