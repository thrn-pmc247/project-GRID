"""Provider-name normalisation for the incumbent provider master.

`PROVIDER_DESCRIPTION` in PMCare's incumbent master is free text and far from
unique: one chain routinely appears under several spellings (`FOCUS POINT VISION
CARE GROUP SDN BHD` and `FOCUS POINT VISION CARE GROUP` are the same chain), and
roughly one name in eight ends in a parenthesised branch qualifier such as
`KLINIK SUREN (TMN KERAMAT)`.

This module derives three comparison forms and never discards the raw value:

* ``name_normalised`` -- uppercased, punctuation collapsed to single spaces,
  corporate suffixes stripped; the branch qualifier is retained inline without
  its brackets.
* ``chain_base_name`` -- the same form with the trailing branch qualifier
  removed, so every branch of a chain shares one grouping key.
* ``branch_qualifier`` / ``branch_qualifier_expanded`` -- the trailing locality
  or branch marker as found, and with whole-token abbreviations expanded.

Both qualifier forms are kept because the incumbent master mixes them: the same
branch appears as `(TMN KERAMAT)` and `(TAMAN KERAMAT)`, and downstream matching
needs to compare either spelling.

Clinic names are business data, not personal data (`docs/context/compliance-pdpa.md`);
practitioner names are held separately and are not handled here.

Rules: `docs/context/malaysian-data-conventions.md` and the
`malaysian-address-normalisation` skill.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

#: Whole-token abbreviations expanded inside a branch qualifier. Malaysian
#: localities are abbreviated inconsistently in the incumbent master, so both the
#: found form and the expanded form are retained on :class:`NameParts`.
#: `LBH` expands to `LEBOH` here because that is the spelling carried by the
#: incumbent branch qualifiers (for example `LBH AMPANG` -> `LEBOH AMPANG`);
#: `grid.normalise.addresses` follows the skill file and uses `LEBUH` for street
#: lines. Both spellings occur in Malaysian addressing.
ABBREVIATIONS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "TMN": "TAMAN",
        "SG": "SUNGAI",
        "JLN": "JALAN",
        "LBH": "LEBOH",
        "BDR": "BANDAR",
        "KG": "KAMPUNG",
    }
)

#: Trailing corporate suffixes stripped from the comparison forms, longest first.
#: Stripping is what collapses `FOCUS POINT VISION CARE GROUP SDN BHD` and
#: `FOCUS POINT VISION CARE GROUP` onto one chain key.
_CORPORATE_SUFFIXES: Final[tuple[tuple[str, ...], ...]] = (
    ("SDN", "BHD", "PLT"),
    ("SDN", "BHD"),
    ("BHD",),
    ("PLT",),
    ("ENTERPRISES",),
    ("ENTERPRISE",),
    ("GROUP",),
)

#: Every word that appears in a corporate suffix. A name built only from these
#: (`SDN BHD` on its own) is left alone -- stripping it would leave an empty key.
_SUFFIX_WORDS: Final[frozenset[str]] = frozenset(
    word for suffix in _CORPORATE_SUFFIXES for word in suffix
)

#: `(M)` in `ENGLAND OPTICAL GROUP (M) SDN BHD` marks the Malaysian entity of a
#: corporate name. It is never a branch qualifier, so it is removed wherever it
#: appears before the trailing group is examined.
_COUNTRY_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    r"\(\s*(?:M|MSIA|MALAYSIA)\s*\.?\s*\)", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class NameParts:
    """Comparison forms derived from one raw provider name.

    Attributes:
        name_raw: The input verbatim (empty string when the input was ``None``).
        name_normalised: Uppercased, punctuation-collapsed, corporate-suffix-stripped
            form, branch qualifier retained inline without brackets.
        chain_base_name: ``name_normalised`` without the branch qualifier -- the
            grouping key for a chain.
        branch_qualifier: Trailing parenthesised qualifier as found (uppercased and
            whitespace-collapsed only), or ``None`` when the name carries none.
        branch_qualifier_expanded: ``branch_qualifier`` with whole-token
            abbreviations from :data:`ABBREVIATIONS` expanded, or ``None``.
    """

    name_raw: str
    name_normalised: str
    chain_base_name: str
    branch_qualifier: str | None
    branch_qualifier_expanded: str | None


def parse_provider_name(raw: str | None) -> NameParts:
    """Split a raw provider name into its comparison forms.

    Parsing is best-effort and never raises on messy input: a ``None``, empty or
    whitespace-only name yields empty comparison forms and ``None`` qualifiers,
    while ``name_raw`` still carries the input verbatim.

    Only a *trailing* parenthesised group is treated as a branch qualifier.
    A mid-name group (`... (M) SDN BHD`) is not, and a country marker is dropped
    outright. Nested brackets are handled by matching the final closing bracket,
    so `KLINIK ABC (TMN A (FASA 2))` yields the whole outer group.

    Args:
        raw: The `PROVIDER_DESCRIPTION` value, which may be ``None`` or blank.

    Returns:
        The derived :class:`NameParts`.

    Examples:
        >>> parse_provider_name("KLINIK SUREN (TMN KERAMAT)").chain_base_name
        'KLINIK SUREN'
        >>> parse_provider_name("KLINIK SUREN (TMN KERAMAT)").branch_qualifier_expanded
        'TAMAN KERAMAT'
    """
    name_raw = raw if raw is not None else ""
    if not name_raw.strip():
        return NameParts(
            name_raw=name_raw,
            name_normalised="",
            chain_base_name="",
            branch_qualifier=None,
            branch_qualifier_expanded=None,
        )

    without_country = _COUNTRY_MARKER_RE.sub(" ", name_raw.strip())
    stem, qualifier_source = _split_trailing_group(without_country)

    stem_tokens = _tokenise(stem)
    qualifier_tokens = _tokenise(qualifier_source) if qualifier_source is not None else ()

    # A name that is nothing but a bracketed group (`(TMN B)`) has no stem to
    # qualify, so the group is the name rather than a branch marker.
    if not stem_tokens:
        stem_tokens = qualifier_tokens
        qualifier_tokens = ()

    chain_tokens = _strip_corporate_suffixes(stem_tokens)
    chain_base_name = " ".join(chain_tokens)
    name_normalised = " ".join((*chain_tokens, *qualifier_tokens))

    branch_qualifier = " ".join(qualifier_tokens) if qualifier_tokens else None
    branch_qualifier_expanded = (
        " ".join(_expand_tokens(qualifier_tokens)) if qualifier_tokens else None
    )

    return NameParts(
        name_raw=name_raw,
        name_normalised=name_normalised,
        chain_base_name=chain_base_name,
        branch_qualifier=branch_qualifier,
        branch_qualifier_expanded=branch_qualifier_expanded,
    )


def _split_trailing_group(text: str) -> tuple[str, str | None]:
    """Split a trailing parenthesised group off the end of a name.

    Args:
        text: The name to split.

    Returns:
        A ``(stem, group_contents)`` pair. ``group_contents`` is ``None`` when the
        name does not end in a balanced bracket group.
    """
    stripped = text.rstrip()
    if not stripped.endswith(")"):
        return text, None

    depth = 0
    for index in range(len(stripped) - 1, -1, -1):
        char = stripped[index]
        if char == ")":
            depth += 1
        elif char == "(":
            depth -= 1
            if depth == 0:
                return stripped[:index], stripped[index + 1 : -1]
    # Unbalanced brackets: treat the whole string as the stem.
    return text, None


def _tokenise(text: str) -> tuple[str, ...]:
    """Uppercase text and collapse every non-alphanumeric run into a token break.

    Args:
        text: Arbitrary free text.

    Returns:
        The uppercased alphanumeric tokens, in order.
    """
    cleaned = "".join(char if char.isalnum() else " " for char in text.upper())
    return tuple(cleaned.split())


def _strip_corporate_suffixes(tokens: Sequence[str]) -> tuple[str, ...]:
    """Repeatedly strip trailing corporate suffixes from a token sequence.

    A name is never stripped away entirely: `SDN BHD` on its own is returned
    unchanged, because an empty chain key would collapse unrelated providers.

    Args:
        tokens: Normalised name tokens.

    Returns:
        The tokens with trailing corporate suffixes removed.
    """
    result = tuple(tokens)
    if all(token in _SUFFIX_WORDS for token in result):
        return result
    stripped = True
    while stripped:
        stripped = False
        for suffix in _CORPORATE_SUFFIXES:
            if len(result) > len(suffix) and result[-len(suffix) :] == suffix:
                result = result[: -len(suffix)]
                stripped = True
                break
    return result


def _expand_tokens(tokens: Iterable[str]) -> tuple[str, ...]:
    """Expand whole-token abbreviations, never a substring of a longer word.

    Args:
        tokens: Normalised tokens.

    Returns:
        The tokens with any exact :data:`ABBREVIATIONS` key replaced; `SGRIA`
        stays `SGRIA` because only whole tokens are matched.
    """
    return tuple(ABBREVIATIONS.get(token, token) for token in tokens)
