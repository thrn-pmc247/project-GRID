"""Table-driven cases for provider-name normalisation.

All fixtures are clinic/company names (business data) or synthetic strings --
never practitioner names, phone numbers or personal addresses
(`docs/context/conventions.md`, CLAUDE.md guardrail 5).
"""

from __future__ import annotations

import pytest

from grid.normalise.names import ABBREVIATIONS, parse_provider_name

# (raw, chain_base_name, branch_qualifier, branch_qualifier_expanded)
BRANCH_QUALIFIER_CASES: list[tuple[str, str, str | None, str | None]] = [
    ("KLINIK SUREN (TMN KERAMAT)", "KLINIK SUREN", "TMN KERAMAT", "TAMAN KERAMAT"),
    ("SABAK DISPENSARY (SG BESAR)", "SABAK DISPENSARY", "SG BESAR", "SUNGAI BESAR"),
    (
        "KLINIK LIAN & NORANA (LBH AMPANG)",
        "KLINIK LIAN NORANA",
        "LBH AMPANG",
        "LEBOH AMPANG",
    ),
    ("MOMENT HOLDING SDN BHD (AUSTIN)", "MOMENT HOLDING", "AUSTIN", "AUSTIN"),
    (
        "PROMEDICS MEDICAL CENTRE (MENARA PROMET)",
        "PROMEDICS MEDICAL CENTRE",
        "MENARA PROMET",
        "MENARA PROMET",
    ),
    (
        "KLINIK ROS DAN RAKAN-RAKAN (TMN SENTUL UTAMA)",
        "KLINIK ROS DAN RAKAN RAKAN",
        "TMN SENTUL UTAMA",
        "TAMAN SENTUL UTAMA",
    ),
    ("KLINIK ALAM MEDIC (CHOW KIT)", "KLINIK ALAM MEDIC", "CHOW KIT", "CHOW KIT"),
    (
        "KLINIK DR. ZULKIFLI (TMN DATUK SENU)",
        "KLINIK DR ZULKIFLI",
        "TMN DATUK SENU",
        "TAMAN DATUK SENU",
    ),
]


@pytest.mark.parametrize(
    ("raw", "chain_base_name", "qualifier", "qualifier_expanded"),
    BRANCH_QUALIFIER_CASES,
)
def test_trailing_branch_qualifier_is_extracted(
    raw: str,
    chain_base_name: str,
    qualifier: str | None,
    qualifier_expanded: str | None,
) -> None:
    """Every real branch-qualifier shape in the incumbent master parses."""
    parts = parse_provider_name(raw)
    assert parts.chain_base_name == chain_base_name
    assert parts.branch_qualifier == qualifier
    assert parts.branch_qualifier_expanded == qualifier_expanded
    assert parts.name_raw == raw


def test_focus_point_spellings_share_one_chain_key() -> None:
    """The two spellings of one chain must collapse onto a single chain key.

    `FOCUS POINT VISION CARE GROUP SDN BHD` (104 rows) and
    `FOCUS POINT VISION CARE GROUP` (87 rows) are the same chain; stripping the
    corporate suffixes before grouping is what merges them.
    """
    with_suffix = parse_provider_name("FOCUS POINT VISION CARE GROUP SDN BHD")
    without_suffix = parse_provider_name("FOCUS POINT VISION CARE GROUP")
    assert with_suffix.chain_base_name == without_suffix.chain_base_name
    assert with_suffix.chain_base_name == "FOCUS POINT VISION CARE"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("KLINIK MEDIVIRON", "KLINIK MEDIVIRON"),
        ("klinik mediviron", "KLINIK MEDIVIRON"),
        ("  KLINIK   MEDIVIRON  ", "KLINIK MEDIVIRON"),
        ("U.N.I KLINIK", "U N I KLINIK"),
        ("POLIKLINIK DR AZHAR DAN RAKAN-RAKAN", "POLIKLINIK DR AZHAR DAN RAKAN RAKAN"),
        ("KLINIK PERGIGIAN TIEW", "KLINIK PERGIGIAN TIEW"),
        ("POLIKLINIK PENAWAR", "POLIKLINIK PENAWAR"),
    ],
)
def test_case_whitespace_and_punctuation_are_collapsed(raw: str, expected: str) -> None:
    parts = parse_provider_name(raw)
    assert parts.name_normalised == expected
    assert parts.chain_base_name == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("KLINIK ALPHA SDN BHD", "KLINIK ALPHA"),
        ("KLINIK ALPHA SDN. BHD.", "KLINIK ALPHA"),
        ("KLINIK ALPHA BHD", "KLINIK ALPHA"),
        ("KLINIK ALPHA ENTERPRISE", "KLINIK ALPHA"),
        ("KLINIK ALPHA ENTERPRISES", "KLINIK ALPHA"),
        ("KLINIK ALPHA GROUP", "KLINIK ALPHA"),
        ("KLINIK ALPHA GROUP SDN BHD", "KLINIK ALPHA"),
        ("KLINIK ALPHA SDN BHD PLT", "KLINIK ALPHA"),
        # Suffix words only ever strip from the end.
        ("GROUP HEALTH KLINIK", "GROUP HEALTH KLINIK"),
        # Never strip a name away entirely.
        ("SDN BHD", "SDN BHD"),
    ],
)
def test_corporate_suffixes_are_stripped_from_the_end_only(raw: str, expected: str) -> None:
    assert parse_provider_name(raw).chain_base_name == expected


def test_mid_name_country_marker_is_not_a_branch_qualifier() -> None:
    """`(M)` in `ENGLAND OPTICAL GROUP (M) SDN BHD` marks the Malaysian entity."""
    parts = parse_provider_name("ENGLAND OPTICAL GROUP (M) SDN BHD")
    assert parts.branch_qualifier is None
    assert parts.chain_base_name == "ENGLAND OPTICAL"


def test_country_marker_and_branch_qualifier_together() -> None:
    parts = parse_provider_name("ENGLAND OPTICAL GROUP (M) SDN BHD (AUSTIN)")
    assert parts.chain_base_name == "ENGLAND OPTICAL"
    assert parts.branch_qualifier == "AUSTIN"


@pytest.mark.parametrize(
    ("raw", "chain_base_name", "qualifier"),
    [
        # Nested brackets: the outer trailing group is the qualifier.
        ("KLINIK ABC (TMN A (FASA 2))", "KLINIK ABC", "TMN A FASA 2"),
        # Two groups: only the trailing one qualifies.
        ("KLINIK ABC (KL) (TMN B)", "KLINIK ABC KL", "TMN B"),
        # Unbalanced brackets: nothing is treated as a qualifier.
        ("KLINIK ABC (TMN B", "KLINIK ABC TMN B", None),
        # A name that is nothing but a group is the name, not a qualifier.
        ("(TMN B)", "TMN B", None),
        # Trailing whitespace after the group still parses.
        ("KLINIK ABC (TMN B)   ", "KLINIK ABC", "TMN B"),
    ],
)
def test_bracket_edge_cases(raw: str, chain_base_name: str, qualifier: str | None) -> None:
    parts = parse_provider_name(raw)
    assert parts.chain_base_name == chain_base_name
    assert parts.branch_qualifier == qualifier


@pytest.mark.parametrize(
    ("qualifier_text", "expected"),
    [
        ("TMN KERAMAT", "TAMAN KERAMAT"),
        ("SG BESAR", "SUNGAI BESAR"),
        ("JLN IPOH", "JALAN IPOH"),
        ("LBH AMPANG", "LEBOH AMPANG"),
        ("BDR BARU", "BANDAR BARU"),
        ("KG PANDAN", "KAMPUNG PANDAN"),
        ("TMN SG BULOH", "TAMAN SUNGAI BULOH"),
        # Whole tokens only -- never a substring inside a longer word.
        ("SGRIA", "SGRIA"),
        ("SGRIA JAYA", "SGRIA JAYA"),
        ("JLNX", "JLNX"),
        ("KGB", "KGB"),
        ("TMNU", "TMNU"),
    ],
)
def test_abbreviations_expand_whole_tokens_only(qualifier_text: str, expected: str) -> None:
    parts = parse_provider_name(f"KLINIK ALPHA ({qualifier_text})")
    assert parts.branch_qualifier == qualifier_text
    assert parts.branch_qualifier_expanded == expected


def test_required_abbreviations_are_present() -> None:
    assert dict(ABBREVIATIONS) == {
        "TMN": "TAMAN",
        "SG": "SUNGAI",
        "JLN": "JALAN",
        "LBH": "LEBOH",
        "BDR": "BANDAR",
        "KG": "KAMPUNG",
    }


def test_name_normalised_keeps_the_qualifier_inline() -> None:
    parts = parse_provider_name("MOMENT HOLDING SDN BHD (AUSTIN)")
    assert parts.name_normalised == "MOMENT HOLDING AUSTIN"
    assert parts.chain_base_name == "MOMENT HOLDING"


@pytest.mark.parametrize("raw", [None, "", "   ", "\t\n", "()", "   ()  "])
def test_blank_input_yields_empty_forms_without_raising(raw: str | None) -> None:
    """Missing or empty names must degrade quietly, never raise."""
    parts = parse_provider_name(raw)
    assert parts.name_normalised == ""
    assert parts.chain_base_name == ""
    assert parts.branch_qualifier is None
    assert parts.branch_qualifier_expanded is None


@pytest.mark.parametrize(("raw", "expected"), [(None, ""), ("", ""), ("   ", "   ")])
def test_raw_name_is_retained_verbatim(raw: str | None, expected: str) -> None:
    """`name_raw` is the audit trail: only ``None`` becomes an empty string."""
    assert parse_provider_name(raw).name_raw == expected


def test_encoding_corruption_does_not_raise() -> None:
    """A U+FFFD replacement character is dropped like any other punctuation."""
    parts = parse_provider_name(f"KLINIK ALPHA{chr(0xFFFD)} (TMN B)")
    assert parts.chain_base_name == "KLINIK ALPHA"
    assert parts.branch_qualifier_expanded == "TAMAN B"


def test_name_parts_are_immutable() -> None:
    parts = parse_provider_name("KLINIK ALPHA")
    with pytest.raises(AttributeError):
        setattr(parts, "chain_base_name", "OTHER")  # noqa: B010
