"""Table-driven tests for the PR001 ``REMARKS`` miner.

The remark strings below are verbatim operational notes from PMCare's provider master.
They are business records, but several embed a PMCare staff member's first name, so
``REMARKS`` is classed ``business_embedded_personal`` in `grid.pr001.columns`. Those
names are therefore used only as *input* here — no assertion reads, extracts or restates
one, and `test_supersession_fragments_are_minimal_spans` pins the miner's structural
guarantee that a fragment can only ever be a keyword span or a keyword-to-code span, so a
name cannot leak into a signal in the first place.

Code universes are synthetic and deliberately tiny. PR001.parquet is never read.
"""

from __future__ import annotations

import pytest

from grid.pr001.remarks import (
    SIGNAL_TYPES,
    RemarkSignal,
    SupersessionEdge,
    build_supersession_graph,
    extract_supersessions,
    find_cycles,
    mine_remark,
    resolve_terminal_code,
)

# --------------------------------------------------------------------------------------
# Verbatim remarks and a synthetic code universe
# --------------------------------------------------------------------------------------

R_WRONG_CODE = "WRONG CODE - CHANGE TO 101252"
R_CHANGE_TO_CODE = "CHANGE TO CODE 201026"
R_PAREN_SPACED = "TERMINATE CHANGE TO NEW CODE (102382)-AFIQAH 12022026"
R_PAREN_TIGHT = "TERMINATE CHANGE TO NEW CODE(206328)-AFIQAH 19062026/TAKE "
R_PAREN_PREFIXED = "JOB0-065835/TERMINATE CHANGE TO NEW CODE(206328)-AFIQAH 19062026"
R_DISTANT_CODE = "TERMINATE : CHANGE TO SOUTHERN AND CURRENTLY PH026 - EMAIL ROZITA 11.1"
R_NO_CODE = "GP NON PANEL 22102015//TERMINATE - CHANGE TO NEW PANEL CODE EMAIL AFIQ"
R_TRUNCATED = "CREATE CODE - NON PANEL EMAIL DALILAH @20122024//TERMINATE-CHANGE TO N"
R_REAPPOINTMENT = "RA 04/06/03 (TERM 26/05/00) FOR HLPC101001"
R_NEW_PROVIDER_FILE = "NEW DENTAL PROVIDER - FILE 05/01/2023"

ALL_REAL_REMARKS = (
    R_WRONG_CODE,
    R_CHANGE_TO_CODE,
    R_PAREN_SPACED,
    R_PAREN_TIGHT,
    R_PAREN_PREFIXED,
    R_DISTANT_CODE,
    R_NO_CODE,
    R_TRUNCATED,
    R_REAPPOINTMENT,
    R_NEW_PROVIDER_FILE,
)

KNOWN_CODES: frozenset[str] = frozenset(
    {
        "0101252",
        "101252",
        "0201025",
        "201026",
        "0102381",
        "102382",
        "0206327",
        "206328",
        "PH025",
        "PH026",
        "HLPC101001",
        # Date-shaped decoys that are also plausible provider codes.
        "12022026",
        "19062026",
        "20122024",
        "120226",
    }
)


def pattern_ids(signals: list[RemarkSignal]) -> list[str]:
    """Return the pattern ids of ``signals``, preserving order."""
    return [signal.pattern_id for signal in signals]


def edge(superseded: str, superseding: str, confidence: float = 0.9) -> SupersessionEdge:
    """Build a bare edge for graph tests, where only the two endpoints matter."""
    return SupersessionEdge(
        superseded_code=superseded,
        superseding_code=superseding,
        evidence="synthetic",
        pattern_id="supersede.change_to_paren",
        confidence=confidence,
    )


# --------------------------------------------------------------------------------------
# Signal-type coverage
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("remark", "expected_pattern_id", "expected_signal_type", "expected_value"),
    [
        (R_WRONG_CODE, "keying.wrong_code", "keying_error", None),
        ("WRONGLY KEYIN", "keying.wrongly_keyin", "keying_error", None),
        ("DUPLICATE - ALREADY IN CMS", "duplicate.already_in_cms", "known_duplicate", "CMS"),
        ("DUPLICATE - ALREADY IN CMS", "duplicate.keyword", "duplicate_flag", None),
        ("CLINIC CLOSED 31/12/2024", "closed.keyword", "closed", None),
        ("RELOCATED TO NEW PREMISES", "relocation.keyword", "relocation", None),
        (R_NEW_PROVIDER_FILE, "new_provider.keyword", "new_provider", "DENTAL"),
        (R_NEW_PROVIDER_FILE, "file.file_date", "file_or_onboarding_date", "05/01/2023"),
        (R_REAPPOINTMENT, "reappointment.ra_prefix", "reappointment", "04/06/03"),
        (R_REAPPOINTMENT, "reappointment.ra_term_date", "reappointment", "26/05/00"),
        (
            R_REAPPOINTMENT,
            "reappointment.ra_cross_reference",
            "reappointment",
            "HLPC101001",
        ),
        (R_PAREN_SPACED, "supersede.change_to_paren", "code_supersession", "102382"),
        (R_NO_CODE, "supersede.keyword_unresolved", "code_supersession", None),
    ],
)
def test_rule_fires_with_expected_type_and_value(
    remark: str,
    expected_pattern_id: str,
    expected_signal_type: str,
    expected_value: str | None,
) -> None:
    """Each documented rule fires and carries the right type, value and vocabulary."""
    matches = [
        signal
        for signal in mine_remark("0102381", remark, KNOWN_CODES)
        if signal.pattern_id == expected_pattern_id
    ]
    assert len(matches) == 1, f"{expected_pattern_id} did not fire exactly once"
    signal = matches[0]
    assert signal.signal_type == expected_signal_type
    assert signal.signal_type in SIGNAL_TYPES
    assert signal.extracted_value == expected_value


def test_every_signal_type_in_the_vocabulary_is_reachable() -> None:
    """The vocabulary is closed: no member is aspirational and none is undeclared."""
    produced: set[str] = set()
    corpus = (
        *ALL_REAL_REMARKS,
        "WRONGLY KEYIN",
        "DUPLICATE - ALREADY IN CMS",
        "CLINIC CLOSED 31/12/2024",
        "RELOCATED TO NEW PREMISES",
    )
    for remark in corpus:
        for signal in mine_remark("0999999", remark, KNOWN_CODES):
            produced.add(signal.signal_type)
    assert produced == SIGNAL_TYPES


def test_reappointment_cross_reference_never_becomes_an_edge() -> None:
    """A reappointment cites a prior code; it does not say the code was replaced."""
    assert extract_supersessions("0999999", R_REAPPOINTMENT, KNOWN_CODES) == []


def test_reappointment_cross_reference_confidence_tracks_resolution() -> None:
    """An unresolvable cross-reference is kept but demoted, never dropped or inflated."""
    (signal,) = [
        s
        for s in mine_remark("0999999", R_REAPPOINTMENT, frozenset())
        if s.pattern_id == "reappointment.ra_cross_reference"
    ]
    assert signal.extracted_value == "HLPC101001"
    assert signal.confidence == 0.50


# --------------------------------------------------------------------------------------
# Supersession extraction
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider_code", "remark", "expected_target", "expected_pattern_id", "expected_confidence"),
    [
        (
            "0102381",
            R_PAREN_SPACED,
            "102382",
            "supersede.change_to_paren",
            0.90,
        ),
        (
            "0206327",
            R_PAREN_TIGHT,
            "206328",
            "supersede.change_to_paren",
            0.90,
        ),
        (
            "0206327",
            R_PAREN_PREFIXED,
            "206328",
            "supersede.change_to_paren",
            0.90,
        ),
        (
            "0201025",
            R_CHANGE_TO_CODE,
            "201026",
            "supersede.change_to_bare",
            0.75,
        ),
        (
            "0101252",
            R_WRONG_CODE,
            "101252",
            "supersede.change_to_bare",
            0.60,
        ),
    ],
)
def test_supersession_edge_is_extracted(
    provider_code: str,
    remark: str,
    expected_target: str,
    expected_pattern_id: str,
    expected_confidence: float,
) -> None:
    """Every observed supersession form resolves to exactly one graded edge."""
    edges = extract_supersessions(provider_code, remark, KNOWN_CODES)
    assert len(edges) == 1
    assert edges[0].superseded_code == provider_code
    assert edges[0].superseding_code == expected_target
    assert edges[0].pattern_id == expected_pattern_id
    assert edges[0].confidence == expected_confidence
    assert expected_target in edges[0].evidence


def test_prefixed_note_does_not_contribute_its_own_number() -> None:
    """A code from an adjacent ``/``-delimited note is never attributed to this keyword."""
    edges = extract_supersessions("0206327", R_PAREN_PREFIXED, KNOWN_CODES | {"065835"})
    assert [e.superseding_code for e in edges] == ["206328"]


@pytest.mark.parametrize(
    ("provider_code", "remark"),
    [
        ("0999991", R_NO_CODE),
        ("0999992", R_TRUNCATED),
        ("PH025", R_DISTANT_CODE),
    ],
)
def test_keyword_without_a_resolvable_code_yields_a_signal_but_no_edge(
    provider_code: str, remark: str
) -> None:
    """The human sees the miss; the graph never absorbs a guess."""
    assert extract_supersessions(provider_code, remark, KNOWN_CODES) == []
    unresolved = [
        signal
        for signal in mine_remark(provider_code, remark, KNOWN_CODES)
        if signal.pattern_id == "supersede.keyword_unresolved"
    ]
    assert len(unresolved) == 1
    assert unresolved[0].signal_type == "code_supersession"
    assert unresolved[0].extracted_value is None
    assert unresolved[0].confidence == 0.30


def test_distant_code_is_a_deliberate_recall_loss() -> None:
    """``PH026`` sits four tokens past the keyword, beyond the precision window."""
    assert "PH026" in KNOWN_CODES
    assert extract_supersessions("PH025", R_DISTANT_CODE, KNOWN_CODES) == []


def test_no_self_edge_when_the_remark_cites_the_rows_own_code() -> None:
    """A row quoting its own code must not become a self-referential edge."""
    assert extract_supersessions("102382", R_PAREN_SPACED, KNOWN_CODES) == []
    signals = mine_remark("102382", R_PAREN_SPACED, KNOWN_CODES)
    assert "supersede.keyword_unresolved" in pattern_ids(signals)


def test_self_edge_rejection_still_allows_a_later_real_target() -> None:
    """Skipping a self-reference continues the scan rather than abandoning it.

    The later target is graded 0.50 because it sits two tokens out. Note it is *not*
    date-shaped: a six-digit target at distance two, with no code cue before it, would be
    rejected by the date guard instead — the two rules compose, deliberately.
    """
    edges = extract_supersessions(
        "0101252", "CHANGE TO CODE 0101252 PH036", frozenset({"0101252", "PH036"})
    )
    assert [e.superseding_code for e in edges] == ["PH036"]
    assert edges[0].confidence == 0.50


def test_eight_digit_action_date_is_never_mistaken_for_a_code() -> None:
    """``12022026`` is a DDMMYYYY stamp; with the real code absent, no edge may form."""
    assert extract_supersessions("0102381", R_PAREN_SPACED, frozenset({"12022026"})) == []


def test_six_digit_date_without_a_code_cue_is_rejected() -> None:
    """``120226`` two tokens out, with no ``(``/``CODE``/``TO`` cue, reads as a date."""
    remark = "TERMINATE CHANGE TO NEW CODE (109999)-EMAIL 120226"
    assert extract_supersessions("0102381", remark, frozenset({"120226"})) == []


def test_six_digit_code_directly_after_a_cue_is_accepted() -> None:
    """The one genuine bare success must survive the date guard: 101252 reads as 10/12/52."""
    edges = extract_supersessions("0101252", R_WRONG_CODE, frozenset({"101252"}))
    assert [e.superseding_code for e in edges] == ["101252"]


def test_empty_known_codes_disables_edges_but_not_signals() -> None:
    """Code resolution is gated entirely on the caller's universe."""
    assert extract_supersessions("0102381", R_PAREN_SPACED, frozenset()) == []
    signals = mine_remark("0102381", R_PAREN_SPACED, frozenset())
    assert pattern_ids(signals) == ["supersede.keyword_unresolved"]


@pytest.mark.parametrize("remark", [None, "", "   ", "\t\n"])
def test_blank_remarks_yield_nothing(remark: str | None) -> None:
    """Null and blank are normal in a 27,052-of-33,643 fill rate, not errors."""
    assert mine_remark("0102381", remark, KNOWN_CODES) == []
    assert extract_supersessions("0102381", remark, KNOWN_CODES) == []


# --------------------------------------------------------------------------------------
# Auditability and determinism
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("remark", ALL_REAL_REMARKS)
def test_every_signal_is_auditable(remark: str) -> None:
    """Every signal carries a non-empty fragment, a known type and honest confidence."""
    for signal in mine_remark("0999999", remark, KNOWN_CODES):
        assert signal.provider_code == "0999999"
        assert signal.raw_fragment.strip()
        assert signal.raw_fragment in remark
        assert signal.signal_type in SIGNAL_TYPES
        assert signal.pattern_id
        assert 0.0 < signal.confidence < 1.0, "no rule may claim certainty"


@pytest.mark.parametrize("remark", ALL_REAL_REMARKS)
def test_supersession_fragments_are_minimal_spans(remark: str) -> None:
    """PDPA minimisation: a fragment is a keyword span or a keyword-to-code span only.

    This is the structural reason a staff name can never reach a signal — the miner never
    captures a free window of trailing text.
    """
    for signal in mine_remark("0999999", remark, KNOWN_CODES):
        if signal.signal_type != "code_supersession":
            continue
        fragment = signal.raw_fragment.upper()
        if signal.extracted_value is None:
            assert fragment.startswith("CHANGE"), fragment
            assert fragment.endswith(("TO", "CODE")), fragment
        else:
            assert fragment.rstrip(")").endswith(signal.extracted_value.upper()), fragment


@pytest.mark.parametrize("remark", ALL_REAL_REMARKS)
def test_output_order_is_deterministic(remark: str) -> None:
    """Byte-identical reruns: ordering is a total order over ``(pattern_id, offset)``."""
    first = mine_remark("0999999", remark, KNOWN_CODES)
    second = mine_remark("0999999", remark, frozenset(reversed(sorted(KNOWN_CODES))))
    assert first == second
    assert pattern_ids(first) == sorted(pattern_ids(first))
    assert extract_supersessions("0999999", remark, KNOWN_CODES) == extract_supersessions(
        "0999999", remark, KNOWN_CODES
    )


def test_multiple_rules_on_one_remark_sort_by_pattern_id() -> None:
    """Cross-rule ordering is stable and independent of rule-table order."""
    signals = mine_remark("0101252", R_WRONG_CODE, KNOWN_CODES)
    assert pattern_ids(signals) == ["keying.wrong_code", "supersede.change_to_bare"]


# --------------------------------------------------------------------------------------
# Graph helpers
# --------------------------------------------------------------------------------------


def test_build_supersession_graph_indexes_and_sorts() -> None:
    """Keys and adjacency lists are sorted so the graph serialises identically."""
    graph = build_supersession_graph(
        [edge("C1", "C3"), edge("A1", "B2"), edge("A1", "A2"), edge("A1", "A2")]
    )
    assert list(graph) == ["A1", "C1"]
    assert [e.superseding_code for e in graph["A1"]] == ["A2", "A2", "B2"]
    assert [e.superseding_code for e in graph["C1"]] == ["C3"]


def test_build_supersession_graph_is_empty_for_no_edges() -> None:
    assert build_supersession_graph([]) == {}


def test_resolve_terminal_code_follows_a_chain() -> None:
    """0101252 -> 101252 -> 101253 collapses to the survivor."""
    edges = [edge("0101252", "101252"), edge("101252", "101253")]
    assert resolve_terminal_code("0101252", edges) == "101253"
    assert resolve_terminal_code("101252", edges) == "101253"
    assert resolve_terminal_code("101253", edges) == "101253"


def test_resolve_terminal_code_returns_the_input_for_an_unknown_code() -> None:
    assert resolve_terminal_code("999999", [edge("A1", "B2")]) == "999999"


def test_resolve_terminal_code_does_not_loop_on_a_two_cycle() -> None:
    """Free text produces mutual references; resolution must terminate, not resolve."""
    edges = [edge("0101252", "101252"), edge("101252", "0101252")]
    assert resolve_terminal_code("0101252", edges) == "0101252"
    assert resolve_terminal_code("101252", edges) == "101252"
    assert find_cycles(edges) == [["0101252", "101252"]]


def test_resolve_terminal_code_does_not_loop_on_a_three_cycle() -> None:
    edges = [edge("A1", "B1"), edge("B1", "C1"), edge("C1", "A1")]
    assert resolve_terminal_code("B1", edges) == "B1"
    assert find_cycles(edges) == [["A1", "B1", "C1"]]


def test_resolve_terminal_code_refuses_an_ambiguous_fork() -> None:
    """Two distinct successors is unresolvable; guessing would fabricate a merge."""
    edges = [edge("A1", "B1"), edge("A1", "C1")]
    assert resolve_terminal_code("A1", edges) == "A1"


def test_resolve_terminal_code_tolerates_a_duplicated_edge() -> None:
    """The same edge mined from two remarks is one successor, not a fork."""
    edges = [edge("A1", "B1"), edge("A1", "B1", confidence=0.6)]
    assert resolve_terminal_code("A1", edges) == "B1"


def test_find_cycles_on_an_acyclic_graph_is_empty() -> None:
    assert find_cycles([edge("A1", "B1"), edge("B1", "C1")]) == []
    assert find_cycles([]) == []


def test_find_cycles_reports_a_self_loop() -> None:
    """The extractor never emits one, but the helpers accept edges from any source."""
    assert find_cycles([edge("A1", "A1")]) == [["A1"]]


def test_find_cycles_reports_each_cycle_once_and_deterministically() -> None:
    """Two disjoint cycles plus a tail: canonical start, sorted output, no duplicates."""
    edges = [
        edge("B1", "A1"),
        edge("A1", "B1"),
        edge("D1", "C1"),
        edge("C1", "D1"),
        edge("D1", "E1"),
    ]
    assert find_cycles(edges) == [["A1", "B1"], ["C1", "D1"]]
    assert find_cycles(list(reversed(edges))) == [["A1", "B1"], ["C1", "D1"]]


def test_mined_edges_flow_into_the_graph_helpers() -> None:
    """End to end: two real remarks mine a chain the helpers can collapse."""
    edges = [
        *extract_supersessions("0101252", R_WRONG_CODE, KNOWN_CODES),
        *extract_supersessions("101252", "CHANGE TO NEW CODE (102382)", KNOWN_CODES),
    ]
    assert [(e.superseded_code, e.superseding_code) for e in edges] == [
        ("0101252", "101252"),
        ("101252", "102382"),
    ]
    assert find_cycles(edges) == []
    assert resolve_terminal_code("0101252", edges) == "102382"
