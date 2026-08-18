"""Mine PNM's free-text ``REMARKS`` into small, auditable, high-precision signals.

``REMARKS`` is the only column in PR001 that records PNM's *own* duplicate-resolution
history — it is PNM telling us, in prose, which records are the same clinic. The most
valuable thing in it is **code supersession**: a directed edge saying "this provider code
was replaced by that one".

Calibration
-----------
The field was profiled over the 27,052 real (non-null, non-blank) remarks in the
2026-08-05 extract. The measured frequencies govern the design:

===========================  ===========
Pattern                      Occurrences
===========================  ===========
``CLOSED``                           537
``DUPLICATE``                        356
``CHANGE TO`` (any form)             167
``NEW <x> PROVIDER``                  12
``^RA `` (reappointment)              11
``WRONG CODE``                         8
``RELOCAT``                            2
``ALREADY IN CMS``                     1
``WRONGLY KEYIN``                      1
===========================  ===========

So this is a **small, high-precision** extractor, not a corpus miner. The governing
instruction is: *an unmatched remark is fine, a wrong supersession edge is not.*

Why the extraction runs backwards from the obvious
--------------------------------------------------
A naive ``CHANGE TO (\\S+)`` matches 167 remarks but only **one** of the captured tokens
is a real ``PROVIDER_CODE`` — the codes are parenthesised or trail a keyword
(``CHANGE TO NEW CODE(206328)``), and ``PROVIDER_CODE`` is not numeric (``GOH``,
``0101252``, ``DEN4022``, ``PH036``, ``N1386``; observed lengths 5-12).

This module therefore never *invents* a code from a regex capture. It tokenises the text
that follows a supersession keyword, keeps only tokens that already exist in the caller's
``known_codes`` universe, and emits an edge only when one resolves. Everything else
degrades to a `RemarkSignal` a human can read.

Two false-positive sources are guarded explicitly:

* **Dates that look like codes.** PNM stamps actions as ``-<initials> 12022026`` or
  ``@20122024``. An eight-digit token that parses as DDMMYYYY is *always* rejected, even
  parenthesised: 8-character codes number only 365 of 33,643, so the recall cost is
  bounded while the false-edge risk is not. A six-digit token that parses as DDMMYY is
  rejected only when it is *not* preceded by a code cue (``(``, ``CODE``, ``TO``, ``NO``)
  — an unconditional rule would kill the one genuine bare success,
  ``CHANGE TO 101252``, whose target reads as 10/12/52.
* **Self-reference.** A remark may cite the row's own code. Such a token is skipped and
  scanning continues; a self-edge is never emitted.

Confidence scale
----------------
Nothing is ever 1.0 — free text mined by regex is never certain.

====  ==========================================================================
0.90  Parenthesised token beside a keyword that names a code, resolving in
      ``known_codes`` (``CHANGE TO NEW CODE (102382)``).
0.85  Structured reappointment header (``RA <date> (TERM <date>)``).
0.80  Parenthesised token beside a keyword that does not name a code; an
      unambiguous literal (``WRONG CODE``, ``ALREADY IN CMS``); a reappointment
      cross-reference that resolves in ``known_codes``.
0.75  Bare token immediately after a keyword that names a code
      (``CHANGE TO CODE 201026``).
0.70  ``CLOSED`` / ``RELOCAT*`` / a ``FILE <date>`` stamp.
0.60  Bare token immediately after a bare ``CHANGE TO``; a bare ``DUPLICATE``;
      ``NEW <x> PROVIDER``.
0.50  Bare token two or three tokens after a keyword; a reappointment
      cross-reference that does not resolve.
0.30  A supersession keyword fired but nothing resolved. Yields a signal so a
      human sees it; **never** yields an edge.
====  ==========================================================================

PDPA
----
``REMARKS`` is classed ``business_embedded_personal`` (see
:mod:`grid.pr001.columns`) because it routinely names PMCare staff. Every
``raw_fragment`` produced here is therefore the **minimal span that fired the rule**,
never a free window of surrounding text — the unresolved-supersession fragment is the
keyword alone for exactly this reason. Signals inherit the column's classification and
must never reach a shareable view, an export or a log line.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Final

__all__ = [
    "SIGNAL_TYPES",
    "RemarkSignal",
    "SupersessionEdge",
    "build_supersession_graph",
    "extract_supersessions",
    "find_cycles",
    "mine_remark",
    "resolve_terminal_code",
]


# --------------------------------------------------------------------------------------
# Public types
# --------------------------------------------------------------------------------------

SIGNAL_TYPES: Final[frozenset[str]] = frozenset(
    {
        "code_supersession",
        "known_duplicate",
        "reappointment",
        "file_or_onboarding_date",
        "keying_error",
        "closed",
        "duplicate_flag",
        "relocation",
        "new_provider",
    }
)
"""The closed signal vocabulary. Every member is evidenced by a counted pattern."""


@dataclass(frozen=True, slots=True)
class RemarkSignal:
    """One auditable observation mined from a single ``REMARKS`` value.

    Attributes:
        provider_code: The row's own ``PROVIDER_CODE``, so signals stay joinable.
        signal_type: A member of `SIGNAL_TYPES`.
        extracted_value: The payload the rule pulled out — a code, a date, a discipline
            — or ``None`` when the rule is a pure flag such as ``closed``.
        raw_fragment: The minimal substring of the remark that produced this signal.
            Mandatory: a human must be able to audit every row without the source text.
        pattern_id: Stable identifier of the rule that fired, e.g.
            ``supersede.change_to_paren``. Stable across releases so counts are
            comparable over time.
        confidence: 0.0-1.0, per the scale in the module docstring. Never 1.0.
    """

    provider_code: str
    signal_type: str
    extracted_value: str | None
    raw_fragment: str
    pattern_id: str
    confidence: float


@dataclass(frozen=True, slots=True)
class SupersessionEdge:
    """A directed "this code was replaced by that one" edge mined from a remark.

    Attributes:
        superseded_code: The row's own code — the one being replaced.
        superseding_code: The replacement code. Always a member of ``known_codes``.
        evidence: The minimal raw fragment that produced the edge.
        pattern_id: Stable identifier of the rule that fired.
        confidence: 0.0-1.0, per the scale in the module docstring.
    """

    superseded_code: str
    superseding_code: str
    evidence: str
    pattern_id: str
    confidence: float


# --------------------------------------------------------------------------------------
# Supersession scanning
# --------------------------------------------------------------------------------------

_SUPERSESSION_KEYWORDS: Final[tuple[str, ...]] = (
    "CHANGE TO NEW PANEL CODE",
    "CHANGED TO NEW PANEL CODE",
    "CHANGE TO NEW CODE",
    "CHANGED TO NEW CODE",
    "CHANGE TO CODE",
    "CHANGED TO CODE",
    "CHANGE TO",
    "CHANGED TO",
)
"""Supersession cues. ``CHANGE TO`` in all its forms is the only counted family (167);
the ``CHANGED`` variants are unevidenced spelling insurance and cost nothing, because a
keyword alone never produces an edge."""

_SUPERSESSION_RE: Final[re.Pattern[str]] = re.compile(
    "|".join(
        keyword.replace(" ", r"\s+")
        for keyword in sorted(_SUPERSESSION_KEYWORDS, key=len, reverse=True)
    ),
    re.IGNORECASE,
)
"""Longest-first alternation, so ``CHANGE TO NEW CODE`` wins over ``CHANGE TO`` at the
same offset and each occurrence is scanned exactly once."""

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9]+")

_SEGMENT_DELIMITER: Final = "/"
"""PNM concatenates independent notes with ``/`` and ``//``. A scan window never crosses
one, so a code from an adjacent note can never be attributed to this keyword."""

_WINDOW_CHARS: Final = 60
_MAX_TOKEN_DISTANCE: Final = 3
"""How many tokens after the keyword may be considered. Three covers every observed
form, including ``CHANGE TO NEW CODE(206328)``. It deliberately does *not* reach
``CHANGE TO SOUTHERN AND CURRENTLY PH026`` (token four) — a documented recall loss taken
in exchange for precision."""

_MIN_CODE_LEN: Final = 3
_MAX_CODE_LEN: Final = 12
"""Cheap prefilter only — ``known_codes`` membership is the real gate. The observed code
length histogram is 5-12, but the profile also cites ``GOH``, so the floor is 3 and short
purely-alphabetic tokens are handled by `_is_code_shaped` instead."""

_CODE_CUE_TOKENS: Final[frozenset[str]] = frozenset({"CODE", "CODES", "TO", "NO"})
"""Tokens that, immediately before a candidate, mark it as a code rather than a date."""


@dataclass(frozen=True, slots=True)
class _SupersessionHit:
    """Internal result of scanning one supersession keyword occurrence."""

    offset: int
    pattern_id: str
    confidence: float
    fragment: str
    target: str | None


def _resolve_code(token: str, known_codes: AbstractSet[str]) -> str | None:
    """Return the canonical member of ``known_codes`` matching ``token``, else ``None``.

    Args:
        token: A raw token lifted from the remark.
        known_codes: The universe of real ``PROVIDER_CODE`` values.

    Returns:
        The matching code exactly as the caller spelled it, or ``None``.
    """
    if token in known_codes:
        return token
    upper = token.upper()
    if upper in known_codes:
        return upper
    return None


def _is_code_shaped(token: str, *, parenthesised: bool) -> bool:
    """Whether ``token`` could be a provider code at all.

    Args:
        token: The candidate token.
        parenthesised: Whether the token sits inside round brackets.

    Returns:
        ``True`` when the token is worth testing against ``known_codes``. Purely
        alphabetic tokens shorter than five characters are rejected unless
        parenthesised, so prose words such as ``NEW`` or ``AND`` can never collide
        with a short code.
    """
    if not _MIN_CODE_LEN <= len(token) <= _MAX_CODE_LEN:
        return False
    return not (token.isalpha() and len(token) < 5 and not parenthesised)


def _looks_like_date(token: str, *, preceded_by_code_cue: bool) -> bool:
    """Whether ``token`` is a PNM action date masquerading as a provider code.

    Args:
        token: The candidate token.
        preceded_by_code_cue: Whether the token is parenthesised or directly follows a
            member of `_CODE_CUE_TOKENS`.

    Returns:
        ``True`` when the token must be rejected. Eight-digit DDMMYYYY is always
        rejected; six-digit DDMMYY is rejected only without a code cue.
    """
    if not token.isdigit():
        return False
    if len(token) == 8:
        day, month, year = int(token[:2]), int(token[2:4]), int(token[4:])
        return 1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2099
    if len(token) == 6 and not preceded_by_code_cue:
        day, month = int(token[:2]), int(token[2:4])
        return 1 <= day <= 31 and 1 <= month <= 12
    return False


def _scan_window(remark: str, start: int) -> str:
    """Return the bounded text after a keyword, never crossing a segment delimiter."""
    text = remark[start : start + _WINDOW_CHARS]
    cut = text.find(_SEGMENT_DELIMITER)
    return text if cut == -1 else text[:cut]


def _is_parenthesised(window: str, match: re.Match[str]) -> bool:
    """Whether the token at ``match`` is wrapped in round brackets within ``window``."""
    before = window[: match.start()].rstrip()
    after = window[match.end() :].lstrip()
    return before.endswith("(") and after.startswith(")")


def _grade(*, parenthesised: bool, distance: int, keyword_names_code: bool) -> tuple[str, float]:
    """Return the ``(pattern_id, confidence)`` for a resolved supersession target."""
    if parenthesised:
        return "supersede.change_to_paren", 0.90 if keyword_names_code else 0.80
    if distance == 1:
        return "supersede.change_to_bare", 0.75 if keyword_names_code else 0.60
    return "supersede.change_to_bare", 0.50


def _scan_supersessions(
    provider_code: str, remark: str, known_codes: AbstractSet[str]
) -> list[_SupersessionHit]:
    """Scan every supersession keyword occurrence in ``remark``.

    Each occurrence yields exactly one hit: either a resolved target, or an unresolved
    marker whose fragment is the keyword alone.
    """
    own_code = provider_code.strip().upper()
    hits: list[_SupersessionHit] = []

    for keyword_match in _SUPERSESSION_RE.finditer(remark):
        keyword_text = keyword_match.group(0)
        keyword_words = keyword_text.upper().split()
        keyword_names_code = keyword_words[-1] in {"CODE", "CODES"}
        keyword_is_cue = keyword_words[-1] in _CODE_CUE_TOKENS

        window = _scan_window(remark, keyword_match.end())
        previous_token: str | None = None
        resolved_hit: _SupersessionHit | None = None

        for distance, token_match in enumerate(_TOKEN_RE.finditer(window), start=1):
            if distance > _MAX_TOKEN_DISTANCE:
                break
            token = token_match.group(0)
            parenthesised = _is_parenthesised(window, token_match)
            cue = parenthesised or (
                previous_token.upper() in _CODE_CUE_TOKENS
                if previous_token is not None
                else keyword_is_cue
            )
            previous_token = token

            if not _is_code_shaped(token, parenthesised=parenthesised):
                continue
            if _looks_like_date(token, preceded_by_code_cue=cue):
                continue
            resolved = _resolve_code(token, known_codes)
            if resolved is None or resolved.strip().upper() == own_code:
                continue

            tail = window[token_match.end() :]
            closing = (len(tail) - len(tail.lstrip()) + 1) if parenthesised else 0
            fragment_end = keyword_match.end() + token_match.end() + closing
            pattern_id, confidence = _grade(
                parenthesised=parenthesised,
                distance=distance,
                keyword_names_code=keyword_names_code,
            )
            resolved_hit = _SupersessionHit(
                offset=keyword_match.start(),
                pattern_id=pattern_id,
                confidence=confidence,
                fragment=remark[keyword_match.start() : fragment_end],
                target=resolved,
            )
            break

        hits.append(
            resolved_hit
            if resolved_hit is not None
            else _SupersessionHit(
                offset=keyword_match.start(),
                pattern_id="supersede.keyword_unresolved",
                confidence=0.30,
                fragment=keyword_text,
                target=None,
            )
        )

    return hits


# --------------------------------------------------------------------------------------
# Single-span rules
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _SimpleRule:
    """A rule whose whole evidence is one regular-expression match."""

    pattern_id: str
    signal_type: str
    pattern: re.Pattern[str]
    confidence: float
    value_group: int | None = None


_SIMPLE_RULES: Final[tuple[_SimpleRule, ...]] = (
    _SimpleRule(
        "keying.wrong_code",
        "keying_error",
        re.compile(r"\bWRONG\s+CODE\b", re.IGNORECASE),
        0.80,
    ),
    _SimpleRule(
        "keying.wrongly_keyin",
        "keying_error",
        re.compile(r"\bWRONGLY\s+KEY\s?(?:IN|ED)\b", re.IGNORECASE),
        0.80,
    ),
    _SimpleRule(
        "duplicate.already_in_cms",
        "known_duplicate",
        re.compile(r"\bALREADY\s+IN\s+(CMS|SYSTEM)\b", re.IGNORECASE),
        0.80,
        1,
    ),
    _SimpleRule(
        "duplicate.keyword",
        "duplicate_flag",
        re.compile(r"(?<!NOT )\bDUPLICATE[DS]?\b", re.IGNORECASE),
        0.60,
    ),
    _SimpleRule(
        "closed.keyword",
        "closed",
        re.compile(r"(?<!NOT )\bCLOSED\b", re.IGNORECASE),
        0.70,
    ),
    _SimpleRule(
        "relocation.keyword",
        "relocation",
        re.compile(r"\bRELOCAT(?:E|ED|ES|ING|ION)\b", re.IGNORECASE),
        0.70,
    ),
    _SimpleRule(
        "new_provider.keyword",
        "new_provider",
        re.compile(r"\bNEW\s+([A-Za-z]+)\s+PROVIDER\b", re.IGNORECASE),
        0.60,
        1,
    ),
    _SimpleRule(
        "file.file_date",
        "file_or_onboarding_date",
        re.compile(r"\bFILE\s+(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})\b", re.IGNORECASE),
        0.70,
        1,
    ),
)

_DATE = r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}"
_RA_ANCHOR: Final[re.Pattern[str]] = re.compile(rf"^\s*RA\s+({_DATE})", re.IGNORECASE)
_RA_TERM: Final[re.Pattern[str]] = re.compile(rf"\(\s*TERM\s+({_DATE})\s*\)", re.IGNORECASE)
_RA_CROSS_REF: Final[re.Pattern[str]] = re.compile(r"\bFOR\s+([A-Za-z0-9]{3,12})\b", re.IGNORECASE)
"""Reappointment header, e.g. ``RA 04/06/03 (TERM 26/05/00) FOR HLPC101001`` (11 rows).
Dates are kept verbatim: the two-digit years are genuinely ambiguous and normalising them
would be a guess, not a parse."""


def _scan_reappointment(
    provider_code: str, remark: str, known_codes: AbstractSet[str]
) -> list[tuple[str, int, RemarkSignal]]:
    """Extract the reappointment date, prior termination date and cross-referenced code.

    Returns:
        ``(pattern_id, offset, signal)`` triples, unsorted. Empty unless the remark opens
        with an ``RA <date>`` header. A cross-reference is *not* a supersession — it
        records why the row was reappointed, not that the code was replaced — so it never
        produces a `SupersessionEdge`.
    """
    anchor = _RA_ANCHOR.search(remark)
    if anchor is None:
        return []

    found: list[tuple[str, int, RemarkSignal]] = [
        (
            "reappointment.ra_prefix",
            anchor.start(),
            RemarkSignal(
                provider_code=provider_code,
                signal_type="reappointment",
                extracted_value=anchor.group(1),
                raw_fragment=anchor.group(0).strip(),
                pattern_id="reappointment.ra_prefix",
                confidence=0.85,
            ),
        )
    ]

    term = _RA_TERM.search(remark)
    if term is not None:
        found.append(
            (
                "reappointment.ra_term_date",
                term.start(),
                RemarkSignal(
                    provider_code=provider_code,
                    signal_type="reappointment",
                    extracted_value=term.group(1),
                    raw_fragment=term.group(0),
                    pattern_id="reappointment.ra_term_date",
                    confidence=0.85,
                ),
            )
        )

    cross_ref = _RA_CROSS_REF.search(remark)
    if cross_ref is not None:
        token = cross_ref.group(1)
        resolved = _resolve_code(token, known_codes)
        found.append(
            (
                "reappointment.ra_cross_reference",
                cross_ref.start(),
                RemarkSignal(
                    provider_code=provider_code,
                    signal_type="reappointment",
                    extracted_value=resolved if resolved is not None else token,
                    raw_fragment=cross_ref.group(0),
                    pattern_id="reappointment.ra_cross_reference",
                    confidence=0.80 if resolved is not None else 0.50,
                ),
            )
        )

    return found


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------


def mine_remark(
    provider_code: str, remark: str | None, known_codes: AbstractSet[str]
) -> list[RemarkSignal]:
    """Mine every signal this module recognises from one ``REMARKS`` value.

    Args:
        provider_code: The row's own ``PROVIDER_CODE``.
        remark: The raw remark text. ``None`` and blank are normal, not errors.
        known_codes: The universe of real ``PROVIDER_CODE`` values. Code extraction is
            gated entirely on membership of this set, so passing an empty set disables
            every code-resolving rule without disabling the keyword signals.

    Returns:
        Signals ordered by ``(pattern_id, fragment offset)`` — a total order, so reruns
        over the same input are byte-identical.
    """
    if remark is None or not remark.strip():
        return []

    collected: list[tuple[str, int, RemarkSignal]] = []

    for hit in _scan_supersessions(provider_code, remark, known_codes):
        collected.append(
            (
                hit.pattern_id,
                hit.offset,
                RemarkSignal(
                    provider_code=provider_code,
                    signal_type="code_supersession",
                    extracted_value=hit.target,
                    raw_fragment=hit.fragment,
                    pattern_id=hit.pattern_id,
                    confidence=hit.confidence,
                ),
            )
        )

    for rule in _SIMPLE_RULES:
        for match in rule.pattern.finditer(remark):
            value = match.group(rule.value_group) if rule.value_group is not None else None
            collected.append(
                (
                    rule.pattern_id,
                    match.start(),
                    RemarkSignal(
                        provider_code=provider_code,
                        signal_type=rule.signal_type,
                        extracted_value=value,
                        raw_fragment=match.group(0),
                        pattern_id=rule.pattern_id,
                        confidence=rule.confidence,
                    ),
                )
            )

    collected.extend(_scan_reappointment(provider_code, remark, known_codes))
    collected.sort(key=lambda entry: (entry[0], entry[1]))
    return [signal for _, _, signal in collected]


def extract_supersessions(
    provider_code: str, remark: str | None, known_codes: AbstractSet[str]
) -> list[SupersessionEdge]:
    """Extract only the supersession edges from one ``REMARKS`` value.

    A keyword that resolves no code yields **no** edge — it surfaces through
    `mine_remark` as ``supersede.keyword_unresolved`` instead, so the human sees the
    miss without the graph absorbing a guess.

    Args:
        provider_code: The row's own ``PROVIDER_CODE`` — the superseded side.
        remark: The raw remark text; ``None`` and blank yield no edges.
        known_codes: The universe of real ``PROVIDER_CODE`` values.

    Returns:
        Edges ordered by ``(pattern_id, fragment offset)``. Never contains a self-edge.
    """
    if remark is None or not remark.strip():
        return []

    hits = sorted(
        _scan_supersessions(provider_code, remark, known_codes),
        key=lambda hit: (hit.pattern_id, hit.offset),
    )
    edges: list[SupersessionEdge] = []
    for hit in hits:
        if hit.target is None:
            continue
        edges.append(
            SupersessionEdge(
                superseded_code=provider_code,
                superseding_code=hit.target,
                evidence=hit.fragment,
                pattern_id=hit.pattern_id,
                confidence=hit.confidence,
            )
        )
    return edges


# --------------------------------------------------------------------------------------
# Graph helpers
# --------------------------------------------------------------------------------------


def build_supersession_graph(
    edges: Iterable[SupersessionEdge],
) -> dict[str, list[SupersessionEdge]]:
    """Index edges by the code they supersede.

    Codes are matched literally — no case folding or zero stripping. ``0101252`` and
    ``101252`` are distinct nodes, which is the whole point of the one remark that links
    them.

    Args:
        edges: Any iterable of edges, from any number of remarks.

    Returns:
        A mapping from superseded code to its outgoing edges. Keys are sorted; each
        adjacency list is sorted by ``(superseding_code, pattern_id, evidence)``.
    """
    graph: dict[str, list[SupersessionEdge]] = {}
    for edge in edges:
        graph.setdefault(edge.superseded_code, []).append(edge)
    for outgoing in graph.values():
        outgoing.sort(key=lambda edge: (edge.superseding_code, edge.pattern_id, edge.evidence))
    return {code: graph[code] for code in sorted(graph)}


def find_cycles(edges: Iterable[SupersessionEdge]) -> list[list[str]]:
    """Enumerate every simple cycle in the supersession graph.

    A directed graph mined from free text will contain cycles — two rows each pointing at
    the other is the commonest form. Callers must inspect these before trusting any
    chain.

    Args:
        edges: Any iterable of edges.

    Returns:
        One list of codes per simple cycle, in traversal order and starting at the
        cycle's lexicographically smallest node, without repeating that node at the end.
        A self-loop appears as a single-element list. The outer list is sorted, so the
        result is deterministic.
    """
    graph = build_supersession_graph(edges)
    adjacency: dict[str, list[str]] = {
        code: sorted({edge.superseding_code for edge in outgoing})
        for code, outgoing in graph.items()
    }
    nodes = sorted(set(adjacency) | {target for row in adjacency.values() for target in row})

    cycles: list[list[str]] = []
    for start in nodes:
        path: list[str] = [start]
        on_path: set[str] = {start}
        frontier: list[Iterator[str]] = [iter(adjacency.get(start, ()))]
        while frontier:
            successor = next(frontier[-1], None)
            if successor is None:
                frontier.pop()
                on_path.discard(path.pop())
                continue
            if successor == start:
                cycles.append(list(path))
            elif successor > start and successor not in on_path:
                path.append(successor)
                on_path.add(successor)
                frontier.append(iter(adjacency.get(successor, ())))
    return sorted(cycles)


def resolve_terminal_code(code: str, edges: Iterable[SupersessionEdge]) -> str:
    """Follow the supersession chain from ``code`` to its end.

    Args:
        code: The starting provider code.
        edges: Any iterable of edges.

    Returns:
        The terminal code of an unambiguous, acyclic chain. Returns ``code`` unchanged
        when the chain cannot be followed to a unique end — either because a node was
        revisited (a cycle) or because a node forks to more than one distinct successor.
        The caller sees the cycle via `find_cycles` and the fork via
        `build_supersession_graph`; this function never guesses between them and never
        loops forever.
    """
    graph = build_supersession_graph(edges)
    visited: set[str] = {code}
    current = code
    while True:
        outgoing = graph.get(current)
        if not outgoing:
            return current
        targets = {edge.superseding_code for edge in outgoing}
        if len(targets) > 1:
            return code
        successor = outgoing[0].superseding_code
        if successor in visited:
            return code
        visited.add(successor)
        current = successor
