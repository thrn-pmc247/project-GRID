"""The branded Queue B workbook, checked by reading the file back.

Every assertion here goes through `openpyxl.load_workbook` rather than inspecting the
in-memory objects. The failures this module exists to catch — a postcode losing its
leading zero, a header fill that is not the brand navy — happen in the serialisation, so
testing the objects instead of the file would test the wrong half.

Three controls are tested in both directions, because a control that cannot fail is not a
control:

* `assert_business_only` passes a clean workbook **and** raises on a leaky one.
* The leak test is itself proved non-vacuous: with the pattern set emptied, the same leaky
  workbook writes successfully.
* The path guard accepts `data/exports` **and** rejects the repository root.

All data here is fabricated. Nothing reads `PR001.parquet` or touches a database.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import fields
from pathlib import Path
from typing import Any, Final

import pytest
from openpyxl import load_workbook

from grid.export.xlsx import (
    ALLOWED_HEADERS,
    BUSINESS_ONLY_NOTICE,
    DRAFT_NOTICE,
    FIRST_DATA_ROW,
    HEADER_ROW,
    NEUTRAL_TPA_NOTICE,
    QUEUE_B_COLUMNS,
    REVIEW_COLUMNS,
    SHEET_COVER,
    SHEET_FUNNEL,
    SHEET_NOTES,
    SHEET_ORDER,
    SHEET_QUEUE_B,
    SHEET_REVIEW,
    SHEET_WIN_BACK,
    WIN_BACK_COLUMNS,
    ExportPathError,
    PersonalDataInExportError,
    WorkbookMeta,
    assert_business_only,
    exports_dir,
    write_queue_b_workbook,
)
from grid.panel.suppression import QueueBPopulation, QueueBRow, Segment, SuppressionReport
from grid.score.priority import Priority, PriorityBand

REPO_ROOT: Final = Path(__file__).resolve().parents[2]

# Brand tokens restated here on purpose. The test is an independent statement of what the
# brand requires; importing the module's own constants would only prove it agrees with
# itself.
BRAND_NAVY: Final = "1F4E79"
BRAND_WHITE: Final = "FFFFFF"
BRAND_ARIAL: Final = "Arial"

EXPECTED_BAND_COLOURS: Final[Mapping[PriorityBand, str]] = {
    PriorityBand.A_CHAIN_FOOTHOLD: "10B981",  # green
    PriorityBand.B_RECENT_RECORD: "F59E0B",  # amber
    PriorityBand.C_CONTACTABLE: "3B82F6",  # blue
    PriorityBand.D_NEEDS_CONTACT: "EF4444",  # red
}

GRID_SHEETS: Final[tuple[str, ...]] = (
    SHEET_QUEUE_B,
    SHEET_WIN_BACK,
    SHEET_REVIEW,
    SHEET_FUNNEL,
    SHEET_NOTES,
)

LEADING_ZERO_POSTCODE: Final = "05000"
"""Alor Setar. Excel reads this as the number 5000 and relocates the clinic to Selangor
unless the cell is written as text — the exact defect `normalise_postcode` exists to
prevent, reintroduced at the last mile."""

ZERO_STATE_CODE: Final = "00"
"""A real state code in the PR001 extract with no known meaning. Becomes ``0`` if the
column is numeric, and then does not join to anything."""

PHONE_SHAPED: Final = "+60123456789"
"""Fabricated. A Malaysian mobile is the likeliest personal-data shape to reach an export,
because it arrives typed into a business free-text field rather than as its own column."""

AS_OF: Final = dt.date(2026, 8, 18)


# --------------------------------------------------------------------------------------
# Fabricated population
# --------------------------------------------------------------------------------------


def _row(
    code: str,
    *,
    name: str = "KLINIK CONTOH",
    postcode: str | None = "40000",
    prefix: str | None = "40",
    state: str = "SL",
    segment: Segment = Segment.NOT_ON_PANEL,
    appointment: dt.datetime | None = None,
    termination: dt.datetime | None = None,
    chain: str | None = None,
    chain_on_panel: int = 0,
    collides: str | None = None,
    flags: tuple[str, ...] = (),
    conflict: bool = False,
    mismatch: bool | None = False,
) -> QueueBRow:
    """One fabricated Queue B row. No value here comes from the real extract."""
    return QueueBRow(
        provider_code=code,
        name_raw=name,
        name_normalised=name.title(),
        chain_base_name=chain,
        branch_qualifier=None,
        address_unit="Lot 1",
        address_street="Jalan Contoh",
        address_locality="Taman Contoh",
        city_raw="Bandar Contoh",
        postcode_clean=postcode,
        postcode_valid=postcode is not None,
        postcode_prefix=prefix,
        postcode_state_mismatch=mismatch,
        state_code=state,
        appointment_date=appointment,
        termination_date=termination,
        segment=segment,
        chain_on_panel_outlets=chain_on_panel,
        collides_with_provider_code=collides,
        review_flags=flags,
        panel_flag_conflict=conflict,
    )


def _year(year: int) -> dt.datetime:
    """An appointment timestamp in a given year."""
    return dt.datetime(year, 3, 15)


CALL_LIST: Final[tuple[QueueBRow, ...]] = (
    _row(
        "GRIDGP0001",
        name="KLINIK CONTOH SATU",
        postcode=LEADING_ZERO_POSTCODE,
        prefix="05",
        state="KD",
        chain="KLINIK CONTOH",
        chain_on_panel=2,
        appointment=_year(2001),
    ),
    _row("GRIDGP0002", name="KLINIK CONTOH DUA", appointment=_year(2003)),
    _row(
        "GRIDGP0003",
        name="KLINIK CONTOH TIGA",
        postcode="10450",
        prefix="10",
        state="PG",
        appointment=_year(2005),
    ),
    _row(
        "GRIDGP0004",
        name="KLINIK CONTOH EMPAT",
        postcode="87000",
        prefix="87",
        state=ZERO_STATE_CODE,
        mismatch=None,
        appointment=_year(2007),
    ),
    _row(
        "GRIDGP0005",
        name="KLINIK CONTOH LIMA",
        postcode="80000",
        prefix="80",
        state="JB",
        appointment=_year(2009),
    ),
)
"""Five rows: one per band, plus one deliberately absent from `PRIORITIES`."""

REVIEW_LIST: Final[tuple[QueueBRow, ...]] = (
    _row(
        "GRIDGP0006",
        name="KLINIK CONTOH ENAM",
        segment=Segment.REVIEW_LIKELY_ON_PANEL,
        collides="GRIDGP9001",
        appointment=_year(2011),
    ),
    _row(
        "GRIDGP0007",
        name="KLINIK CONTOH TUJUH",
        segment=Segment.REVIEW_FLAGGED,
        flags=("closed", "known_duplicate"),
        appointment=_year(2013),
    ),
)

WIN_BACK_LIST: Final[tuple[QueueBRow, ...]] = (
    _row(
        "GRIDGP0008",
        name="KLINIK CONTOH LAPAN",
        segment=Segment.WIN_BACK,
        appointment=_year(2015),
        termination=dt.datetime(2024, 3, 1),
        conflict=True,
    ),
    _row(
        "GRIDGP0009",
        name="KLINIK CONTOH SEMBILAN",
        segment=Segment.WIN_BACK,
        appointment=_year(2016),
        termination=dt.datetime(2025, 6, 15),
    ),
)

MEDIAN_APPOINTMENT_YEAR: Final = 2007
"""The median of the seven not-on-panel years above (2001 … 2013). Chosen so the caveat
sentence on the Notes sheet has a value the test can pin exactly."""

PRIORITIES: Final[Mapping[str, Priority]] = {
    "GRIDGP0001": Priority(
        band=PriorityBand.A_CHAIN_FOOTHOLD,
        reasons=(
            "2 outlets of this chain are already on the PMCare panel (inferred)",
            "a valid phone number is on record",
        ),
    ),
    "GRIDGP0002": Priority(
        band=PriorityBand.B_RECENT_RECORD,
        reasons=("record added 2003 — the freshness of PMCare's record, not of the clinic",),
    ),
    "GRIDGP0003": Priority(
        band=PriorityBand.C_CONTACTABLE,
        reasons=("a valid phone number is on record",),
    ),
    "GRIDGP0004": Priority(
        band=PriorityBand.D_NEEDS_CONTACT,
        reasons=("no valid phone number on record",),
    ),
    # GRIDGP0005 has no priority on purpose: an unranked row must still appear.
}

REPORT: Final = SuppressionReport(
    as_of=AS_OF,
    total_outlets=120,
    gp_rows=60,
    gp_active_as_of=48,
    gp_active_status_code_a=47,
    status_code_disagreements=3,
    on_panel=40,
    not_on_panel=8,
    excluded_superseded=1,
    routed_to_review_flagged=1,
    routed_to_review_likely_on_panel=1,
    win_back=2,
    queue_b_final=5,
)

POPULATION: Final = QueueBPopulation(
    report=REPORT,
    # Reversed on purpose: the workbook must rank the list, not echo its input order.
    call_list=tuple(reversed(CALL_LIST)),
    win_back=WIN_BACK_LIST,
    review=REVIEW_LIST,
)

META: Final = WorkbookMeta(
    title="Queue B — GP clinics not on the PMCare panel",
    as_of=AS_OF,
    generated_at=dt.datetime(2026, 8, 18, 9, 30),
    source_note="Fabricated fixture. Not derived from any PMCare extract.",
    contains_personal_data=False,
    requested_by="Provider Network Management",
    purpose="Panel engagement planning.",
)


# --------------------------------------------------------------------------------------
# Fixtures and helpers
# --------------------------------------------------------------------------------------


@pytest.fixture
def destination(tmp_path: Path) -> Path:
    """A path inside an injected exports directory, so nothing lands in the working tree."""
    return exports_dir(tmp_path) / "queue_b.xlsx"


@pytest.fixture
def written(destination: Path) -> Path:
    """The workbook, written once and read back by the tests that follow."""
    return write_queue_b_workbook(POPULATION, PRIORITIES, path=destination, meta=META)


@pytest.fixture
def workbook(written: Path) -> Iterator[Any]:
    """The workbook as openpyxl reads it back off disk."""
    book = load_workbook(written)
    yield book
    book.close()


def _sheet_values(sheet: Any) -> list[object]:
    """Every non-empty value on one sheet."""
    return [
        value for row in sheet.iter_rows(values_only=True) for value in row if value is not None
    ]


def _harvest(book: Any) -> tuple[list[str], list[object]]:
    """Every header and every value in a workbook, as `assert_business_only` wants them."""
    headers: list[str] = []
    cells: list[object] = []
    for name in book.sheetnames:
        sheet = book[name]
        for index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            for value in row:
                if value is None:
                    continue
                if name != SHEET_COVER and index == HEADER_ROW:
                    headers.append(str(value))
                cells.append(value)
    return headers, cells


def _column_index(sheet: Any, header: str) -> int:
    """The 1-based index of a named column on a grid sheet."""
    for cell in sheet[HEADER_ROW]:
        if cell.value == header:
            return int(cell.column)
    raise AssertionError(f"{sheet.title} has no column named {header!r}")


def _column_values(sheet: Any, header: str) -> list[object]:
    """Every data value under a named column."""
    index = _column_index(sheet, header)
    return [
        sheet.cell(row=row, column=index).value for row in range(FIRST_DATA_ROW, sheet.max_row + 1)
    ]


def _rgb(colour: Any) -> str:
    """The six-digit hex of an openpyxl colour, dropping the alpha byte."""
    return str(colour.rgb)[-6:].upper()


def _leaky_population() -> QueueBPopulation:
    """The same population with a telephone number typed into a business name field.

    This is how a leak actually arrives: not as a new "phone" column, but as a number
    someone put in a free-text field upstream years ago.
    """
    leaky = _row("GRIDGP0099", name=f"KLINIK CONTOH (HUBUNGI {PHONE_SHAPED})")
    return QueueBPopulation(
        report=REPORT,
        call_list=(*CALL_LIST, leaky),
        win_back=WIN_BACK_LIST,
        review=REVIEW_LIST,
    )


# --------------------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------------------


def test_all_six_sheets_are_present(workbook: Any) -> None:
    """Cover, Queue B, Win-back, Review, Suppression funnel, Notes & definitions."""
    assert workbook.sheetnames == list(SHEET_ORDER)
    assert len(SHEET_ORDER) == 6


def test_the_workbook_is_written_where_it_was_asked_for(written: Path, destination: Path) -> None:
    """The returned path is the file that exists, resolved."""
    assert written == destination.resolve()
    assert written.is_file()
    assert written.stat().st_size > 0


@pytest.mark.parametrize("sheet_name", GRID_SHEETS)
def test_header_row_is_navy_with_white_bold_arial(workbook: Any, sheet_name: str) -> None:
    """The brand's table rule, on every grid sheet: navy fill, white bold Arial."""
    sheet = workbook[sheet_name]
    headers = [cell for cell in sheet[HEADER_ROW] if cell.value is not None]
    assert headers, f"{sheet_name} has no header row"

    for cell in headers:
        assert cell.fill.fill_type == "solid", f"{sheet_name}!{cell.coordinate} has no fill"
        assert _rgb(cell.fill.start_color) == BRAND_NAVY
        assert _rgb(cell.font.color) == BRAND_WHITE
        assert cell.font.bold is True
        assert cell.font.name == BRAND_ARIAL


@pytest.mark.parametrize("sheet_name", GRID_SHEETS)
def test_grid_sheets_freeze_the_header_and_filter(workbook: Any, sheet_name: str) -> None:
    """These workbooks are worked, not read: the header stays put and filters are on."""
    sheet = workbook[sheet_name]
    assert sheet.freeze_panes == f"A{FIRST_DATA_ROW}"
    assert sheet.auto_filter.ref is not None
    assert sheet.auto_filter.ref.startswith(f"A{HEADER_ROW}:")


@pytest.mark.parametrize("sheet_name", GRID_SHEETS)
def test_grid_sheets_set_column_widths(workbook: Any, sheet_name: str) -> None:
    """A workbook of ### columns is not a workbook anyone will use."""
    sheet = workbook[sheet_name]
    headers = [cell for cell in sheet[HEADER_ROW] if cell.value is not None]
    for cell in headers:
        dimension = sheet.column_dimensions[cell.column_letter]
        assert dimension.width and dimension.width > 6


@pytest.mark.parametrize("sheet_name", GRID_SHEETS)
def test_body_text_is_arial(workbook: Any, sheet_name: str) -> None:
    """Arial throughout, body as well as headings."""
    sheet = workbook[sheet_name]
    for row in sheet.iter_rows(min_row=FIRST_DATA_ROW):
        for cell in row:
            if cell.value is not None:
                assert cell.font.name == BRAND_ARIAL


# --------------------------------------------------------------------------------------
# Trap 1 — Excel eats leading zeros
# --------------------------------------------------------------------------------------


def test_leading_zero_postcode_survives_as_text(workbook: Any) -> None:
    """``05000`` must come back as the string ``05000``, never the number ``5000``.

    This is the whole reason the postcode column is written in Excel text format. A
    postcode that loses its leading zero does not merely look wrong: 05000 is Alor Setar
    and 5000 is not a Malaysian postcode at all, so the clinic silently changes state.
    """
    sheet = workbook[SHEET_QUEUE_B]
    postcodes = _column_values(sheet, "Postcode")

    assert LEADING_ZERO_POSTCODE in postcodes
    assert 5000 not in postcodes
    for value in postcodes:
        assert isinstance(value, str), f"{value!r} came back as {type(value).__name__}"


def test_zero_state_code_survives_as_text(workbook: Any) -> None:
    """State code ``00`` must not become ``0``. It is a real code in the extract."""
    sheet = workbook[SHEET_QUEUE_B]
    states = _column_values(sheet, "State code")

    assert ZERO_STATE_CODE in states
    assert 0 not in states
    for value in states:
        assert isinstance(value, str)


def test_postcode_prefix_survives_as_text(workbook: Any) -> None:
    """The prefix has the same defect in miniature: ``05`` is a state block, ``5`` is not."""
    sheet = workbook[SHEET_QUEUE_B]
    prefixes = _column_values(sheet, "Postcode prefix")

    assert "05" in prefixes
    for value in prefixes:
        assert isinstance(value, str)


@pytest.mark.parametrize(
    ("sheet_name", "header"),
    [
        (SHEET_QUEUE_B, "Postcode"),
        (SHEET_QUEUE_B, "Postcode prefix"),
        (SHEET_QUEUE_B, "State code"),
        (SHEET_WIN_BACK, "Postcode"),
        (SHEET_WIN_BACK, "State code"),
        (SHEET_REVIEW, "Postcode"),
        (SHEET_REVIEW, "State code"),
    ],
)
def test_zero_sensitive_columns_carry_the_excel_text_format(
    workbook: Any, sheet_name: str, header: str
) -> None:
    """Every list sheet, not only the first one, formats these columns as text.

    Asserting the round-tripped value alone is not enough: a value can survive openpyxl and
    still be reinterpreted the moment a user re-saves the file in Excel. The ``@`` format is
    what stops that, so the format itself is asserted.
    """
    sheet = workbook[sheet_name]
    index = _column_index(sheet, header)
    for row in range(FIRST_DATA_ROW, sheet.max_row + 1):
        assert sheet.cell(row=row, column=index).number_format == "@"


# --------------------------------------------------------------------------------------
# Trap 2 — the path guard
# --------------------------------------------------------------------------------------


def test_path_guard_rejects_the_repository_root() -> None:
    """Check 13 fails the build on any ``*.xlsx`` at the repo root, so the writer refuses.

    Check 13 globs the filesystem rather than the git index, so ``data/`` being gitignored
    does not save a workbook written to the wrong place.
    """
    stray = REPO_ROOT / "queue_b.xlsx"

    with pytest.raises(ExportPathError, match="repository root"):
        write_queue_b_workbook(POPULATION, PRIORITIES, path=stray, meta=META)

    assert not stray.exists(), "the guard must refuse before anything is written"


def test_path_guard_rejects_a_directory_outside_exports(tmp_path: Path) -> None:
    """Anywhere that is not a ``data/exports`` directory is refused."""
    stray = tmp_path / "queue_b.xlsx"

    with pytest.raises(ExportPathError, match="data/exports"):
        write_queue_b_workbook(POPULATION, PRIORITIES, path=stray, meta=META)

    assert not stray.exists()


def test_path_guard_rejects_a_non_xlsx_suffix(tmp_path: Path) -> None:
    """A workbook written as ``.csv`` would trip check 13's other half."""
    stray = exports_dir(tmp_path) / "queue_b.csv"

    with pytest.raises(ExportPathError, match="xlsx"):
        write_queue_b_workbook(POPULATION, PRIORITIES, path=stray, meta=META)


def test_exports_dir_is_injectable(tmp_path: Path) -> None:
    """Tests must be able to point the whole export path at `tmp_path`."""
    assert exports_dir(tmp_path) == (tmp_path / "data" / "exports").resolve()


def test_exports_dir_defaults_to_the_repository_tree() -> None:
    """With no root, the default is ``<repo>/data/exports`` — inside the gitignored tree."""
    default = exports_dir()

    assert default == (REPO_ROOT / "data" / "exports").resolve()
    assert default.name == "exports"
    assert default.parent.name == "data"


def test_the_writer_creates_the_exports_directory(destination: Path) -> None:
    """The guard runs first, then the directory is created. Not the other way round."""
    assert not destination.parent.exists()

    write_queue_b_workbook(POPULATION, PRIORITIES, path=destination, meta=META)

    assert destination.parent.is_dir()


# --------------------------------------------------------------------------------------
# Cover
# --------------------------------------------------------------------------------------


def test_cover_carries_the_draft_notice(workbook: Any) -> None:
    """Every outward artefact is a draft requiring human review, and says so."""
    values = [str(value) for value in _sheet_values(workbook[SHEET_COVER])]
    assert DRAFT_NOTICE in values
    assert any("requires human review" in value for value in values)


def test_cover_states_pmcare_is_a_neutral_administrator(workbook: Any) -> None:
    """Guardrail 9 — never positioned as insurer or treating clinician."""
    values = [str(value) for value in _sheet_values(workbook[SHEET_COVER])]
    assert NEUTRAL_TPA_NOTICE in values
    assert any("not the insurer" in value for value in values)
    assert any("not a treating clinician" in value for value in values)


def test_cover_declares_the_workbook_business_data_only(workbook: Any) -> None:
    """`meta.contains_personal_data` is False, so the cover says so in terms."""
    values = [str(value) for value in _sheet_values(workbook[SHEET_COVER])]
    assert BUSINESS_ONLY_NOTICE in values
    assert any(value.startswith("No — business data only") for value in values)


def test_cover_dates_are_dd_month_yyyy(workbook: Any) -> None:
    """The brand's date format, spelled out in British English."""
    values = [str(value) for value in _sheet_values(workbook[SHEET_COVER])]
    assert "18 August 2026" in values
    assert any(value.startswith("18 August 2026 at 09:30") for value in values)


def test_cover_names_the_source_and_the_title(workbook: Any) -> None:
    """Provenance a reader needs before trusting the numbers."""
    values = [str(value) for value in _sheet_values(workbook[SHEET_COVER])]
    assert META.title in values
    assert META.source_note in values
    assert META.requested_by in values


def test_cover_title_block_is_navy(workbook: Any) -> None:
    """The branded title block, in the primary colour."""
    title = workbook[SHEET_COVER]["A1"]
    assert title.value == META.title
    assert _rgb(title.fill.start_color) == BRAND_NAVY
    assert _rgb(title.font.color) == BRAND_WHITE
    assert title.font.name == BRAND_ARIAL
    assert title.font.bold is True


# --------------------------------------------------------------------------------------
# Queue B
# --------------------------------------------------------------------------------------


def test_queue_b_holds_every_call_list_row(workbook: Any) -> None:
    """Nothing is dropped, including the row with no priority assigned."""
    codes = _column_values(workbook[SHEET_QUEUE_B], "Provider code")
    assert set(codes) == {row.provider_code for row in CALL_LIST}


def test_queue_b_is_ranked_not_echoed(workbook: Any) -> None:
    """The input was reversed; the output must still be A, B, C, D, then unranked."""
    sheet = workbook[SHEET_QUEUE_B]

    assert _column_values(sheet, "Rank") == [1, 2, 3, 4, 5]
    assert _column_values(sheet, "Provider code") == [
        "GRIDGP0001",
        "GRIDGP0002",
        "GRIDGP0003",
        "GRIDGP0004",
        "GRIDGP0005",
    ]


def test_band_colours_follow_the_brand_status_palette(workbook: Any) -> None:
    """Green, amber, blue and red for bands A, B, C and D."""
    sheet = workbook[SHEET_QUEUE_B]
    index = _column_index(sheet, "Priority band")
    seen: set[PriorityBand] = set()

    for row in range(FIRST_DATA_ROW, sheet.max_row + 1):
        cell = sheet.cell(row=row, column=index)
        if cell.value == "Unranked":
            continue
        band = PriorityBand(cell.value)
        seen.add(band)
        assert cell.fill.fill_type == "solid", f"band {band.name} has no status fill"
        assert _rgb(cell.fill.start_color) == EXPECTED_BAND_COLOURS[band]
        assert cell.font.name == BRAND_ARIAL

    assert seen == set(EXPECTED_BAND_COLOURS), "every band must appear in the fixture"


def test_a_row_without_a_priority_is_shown_as_unranked(workbook: Any) -> None:
    """An unranked clinic is a gap in the scoring. Hiding it would hide the gap."""
    bands = _column_values(workbook[SHEET_QUEUE_B], "Priority band")
    assert bands[-1] == "Unranked"


def test_why_this_rank_renders_the_priority_reasons(workbook: Any) -> None:
    """A caller can read why a clinic is near the top, and disagree with it."""
    sheet = workbook[SHEET_QUEUE_B]
    reasons = _column_values(sheet, "Why this rank")

    top = str(reasons[0])
    for fragment in PRIORITIES["GRIDGP0001"].reasons:
        assert fragment in top
    assert "; " in top, "multiple reasons must stay separable"
    assert str(reasons[-1]) == "No ranking signal recorded."


def test_appointment_dates_are_real_dates(workbook: Any) -> None:
    """Written as dates so the column sorts and filters, not as strings that look like them."""
    values = _column_values(workbook[SHEET_QUEUE_B], "Appointment date")
    assert all(isinstance(value, dt.datetime | dt.date) for value in values)


# --------------------------------------------------------------------------------------
# Win-back
# --------------------------------------------------------------------------------------


def test_win_back_is_labelled_a_different_conversation(workbook: Any) -> None:
    """These clinics were terminated. They are not never-engaged prospects."""
    notice = str(workbook[SHEET_WIN_BACK]["A1"].value)

    assert "different conversation" in notice
    assert "terminated" in notice
    assert "not never-engaged" in notice


def test_win_back_counts_the_panel_flag_contradiction(workbook: Any) -> None:
    """Terminated yet still flagged on-panel — the notice says how many, so it is visible.

    On the real extract this is 147 rows. Whatever the number, it is a contradiction in the
    source that a human has to resolve, not something the export should quietly pick a side
    on.
    """
    sheet = workbook[SHEET_WIN_BACK]
    expected = sum(1 for row in WIN_BACK_LIST if row.panel_flag_conflict)

    assert f"{expected:,} of these are terminated yet still flagged on-panel" in str(
        sheet["A1"].value
    )
    assert _column_values(sheet, "Panel flag conflict") == ["Yes", "No"]


def test_win_back_shows_termination_dates(workbook: Any) -> None:
    """The date they left is the whole point of the row."""
    values = _column_values(workbook[SHEET_WIN_BACK], "Termination date")
    assert all(value is not None for value in values)


# --------------------------------------------------------------------------------------
# Review
# --------------------------------------------------------------------------------------


def test_review_sheet_says_not_to_call_from_it(workbook: Any) -> None:
    """These rows must not be called without checking first."""
    notice = str(workbook[SHEET_REVIEW]["A1"].value)
    assert "Do not call" in notice


def test_review_gives_each_row_its_reason(workbook: Any) -> None:
    """Either a colliding provider code, or the REMARKS flags. Never just "review"."""
    sheet = workbook[SHEET_REVIEW]
    reasons = [str(value) for value in _column_values(sheet, "Review reason")]

    collision = next(reason for reason in reasons if "GRIDGP9001" in reason)
    assert "already on panel" in collision

    flagged = next(reason for reason in reasons if "REMARKS" in reason)
    assert "closed" in flagged
    assert "known_duplicate" in flagged

    assert _column_values(sheet, "Collides with provider code")[0] == "GRIDGP9001"
    assert _column_values(sheet, "REMARKS flags")[1] == "closed, known_duplicate"


# --------------------------------------------------------------------------------------
# Suppression funnel
# --------------------------------------------------------------------------------------


def test_funnel_reports_every_field_of_the_report(workbook: Any) -> None:
    """Built from the dataclass's fields, so a new step cannot go unreported.

    The reader has to be able to reconcile the number they are handed rather than trust it,
    which means every step between "all outlets" and "the call list" has to be on the sheet.
    """
    steps = {str(value) for value in _column_values(workbook[SHEET_FUNNEL], "Step")}

    for field in fields(SuppressionReport):
        expected = field.name.replace("_", " ").capitalize()
        assert expected in steps, f"the funnel omits {field.name}"


def test_funnel_carries_the_counts_and_reconciles(workbook: Any) -> None:
    """The chain of numbers, and an explicit statement that they add up."""
    sheet = workbook[SHEET_FUNNEL]
    values = dict(
        zip(
            [str(step) for step in _column_values(sheet, "Step")],
            _column_values(sheet, "Value"),
            strict=True,
        )
    )

    assert values["Total outlets"] == REPORT.total_outlets
    assert values["Gp rows"] == REPORT.gp_rows
    assert values["On panel"] == REPORT.on_panel
    assert values["Not on panel"] == REPORT.not_on_panel
    assert values["Queue b final"] == REPORT.queue_b_final
    assert values["As of"] == "18 August 2026"
    assert values["Funnel reconciles"] == "Yes"
    assert REPORT.reconciles is True


def test_funnel_reports_a_failure_to_reconcile(tmp_path: Path) -> None:
    """A funnel that does not add up says so rather than looking tidy.

    Without this the "Yes" above would be indistinguishable from a cell that always says
    yes.
    """
    broken = SuppressionReport(
        **{
            **{field.name: getattr(REPORT, field.name) for field in fields(SuppressionReport)},
            "queue_b_final": REPORT.queue_b_final + 1,
        }
    )
    population = QueueBPopulation(
        report=broken, call_list=CALL_LIST, win_back=WIN_BACK_LIST, review=REVIEW_LIST
    )
    path = write_queue_b_workbook(
        population, PRIORITIES, path=exports_dir(tmp_path) / "broken.xlsx", meta=META
    )

    book = load_workbook(path)
    try:
        sheet = book[SHEET_FUNNEL]
        row = _column_values(sheet, "Step").index("Funnel reconciles")
        assert _column_values(sheet, "Value")[row] == "No"
    finally:
        book.close()


# --------------------------------------------------------------------------------------
# Notes and definitions
# --------------------------------------------------------------------------------------


def test_notes_documents_every_column_in_the_workbook(workbook: Any) -> None:
    """A column nobody can explain is a column nobody should act on."""
    documented = {str(value) for value in _column_values(workbook[SHEET_NOTES], "Column or note")}
    headers = {column.header for column in (*QUEUE_B_COLUMNS, *WIN_BACK_COLUMNS, *REVIEW_COLUMNS)}

    assert headers <= documented, f"undocumented columns: {sorted(headers - documented)}"


def test_notes_never_leaves_a_column_undocumented(workbook: Any) -> None:
    """The fallback text must not appear — every column has a real note written for it."""
    values = [str(value) for value in _sheet_values(workbook[SHEET_NOTES])]
    assert not [value for value in values if "Not yet documented" in value]


def test_notes_separates_known_from_inferred(workbook: Any) -> None:
    """Chain membership is inferred, and the workbook says so where it is used."""
    sheet = workbook[SHEET_NOTES]
    provenance = dict(
        zip(
            [str(term) for term in _column_values(sheet, "Column or note")],
            [str(value) for value in _column_values(sheet, "Known or inferred")],
            strict=True,
        )
    )

    assert provenance["Chain (inferred)"] == "Inferred"
    assert provenance["Chain outlets on panel (inferred)"] == "Inferred"
    assert provenance["Provider code"] == "Known"
    assert provenance["Postcode"] == "Known"

    meanings = {str(value) for value in _column_values(sheet, "What it means")}
    assert any("same premises keyed twice" in meaning for meaning in meanings)


def test_notes_carries_the_already_engaged_caveat(workbook: Any) -> None:
    """The caveat that stops this being read as a list of never-engaged clinics.

    Every row already carries an appointment date, so PMCare has a provider record for all
    of them. The median is computed from the population in the workbook rather than quoted
    from a profile, so it cannot go stale against the data beside it.
    """
    meanings = [str(value) for value in _column_values(workbook[SHEET_NOTES], "What it means")]
    caveat = next(meaning for meaning in meanings if "median year" in meaning)

    total = len(CALL_LIST) + len(REVIEW_LIST)
    assert f"{total} of the {total} not-on-panel rows" in caveat
    assert f"median year {MEDIAN_APPOINTMENT_YEAR}" in caveat
    assert "not a list of clinics PMCare has never engaged" in caveat


def test_notes_repeats_the_draft_and_neutral_tpa_notices(workbook: Any) -> None:
    """A reader who starts on the Notes sheet still sees both."""
    values = [str(value) for value in _sheet_values(workbook[SHEET_NOTES])]
    assert DRAFT_NOTICE in values
    assert NEUTRAL_TPA_NOTICE in values


# --------------------------------------------------------------------------------------
# PDPA — the business-only control, in both directions
# --------------------------------------------------------------------------------------


def test_every_column_header_is_on_the_allow_list() -> None:
    """A new column has to be added to `ALLOWED_HEADERS` as a separate, reviewable line."""
    for column in (*QUEUE_B_COLUMNS, *WIN_BACK_COLUMNS, *REVIEW_COLUMNS):
        assert column.header in ALLOWED_HEADERS


def test_assert_business_only_passes_a_clean_workbook(workbook: Any) -> None:
    """The workbook this module actually produces carries no personal data."""
    headers, cells = _harvest(workbook)

    assert headers, "there must be headers to check"
    assert len(cells) > 100, "there must be values to scan"
    assert_business_only(headers, cells)


def test_the_workbook_carries_no_contact_column(workbook: Any) -> None:
    """`QueueBRow` holds no phone, name, e-mail or tax identifier. Nothing widens it here."""
    headers, _ = _harvest(workbook)
    lowered = " ".join(headers).lower()

    for forbidden in ("phone", "mobile", "e-mail", "email", "doctor", "tin", "nric"):
        assert forbidden not in lowered


def test_assert_business_only_raises_on_a_phone_shaped_value(workbook: Any) -> None:
    """A telephone number anywhere in the workbook fails the check."""
    headers, cells = _harvest(workbook)

    with pytest.raises(PersonalDataInExportError, match="Malaysian mobile number"):
        assert_business_only(headers, [*cells, f"KLINIK CONTOH {PHONE_SHAPED}"])


def test_assert_business_only_raises_on_an_nric_shaped_value(workbook: Any) -> None:
    """An NRIC is sensitive personal data and has no business in a provider export.

    The sample is assembled at runtime rather than written as a literal. Check 13 of
    `scripts/check_context.py` scans every tracked file for NRIC-shaped strings and does not
    exempt `tests/`; keeping the shape out of the file source satisfies both.
    """
    headers, cells = _harvest(workbook)
    nric_shaped = "-".join(("880101", "14", "5678"))

    with pytest.raises(PersonalDataInExportError, match="NRIC"):
        assert_business_only(headers, [*cells, nric_shaped])


def test_assert_business_only_raises_on_an_email_shaped_value(workbook: Any) -> None:
    """An e-mail address is personal data when it identifies a sole proprietor."""
    headers, cells = _harvest(workbook)

    with pytest.raises(PersonalDataInExportError, match="e-mail"):
        assert_business_only(headers, [*cells, "doktor.contoh@example.invalid"])


def test_assert_business_only_raises_on_a_header_outside_the_allow_list(workbook: Any) -> None:
    """The deliberate route: somebody widens the export to "just add the phone number"."""
    headers, cells = _harvest(workbook)

    with pytest.raises(PersonalDataInExportError, match="allow-list"):
        assert_business_only([*headers, "Contact number"], cells)


def test_the_failure_message_never_quotes_the_value(workbook: Any) -> None:
    """A disclosure warning that reprints the value is a second disclosure."""
    headers, cells = _harvest(workbook)

    with pytest.raises(PersonalDataInExportError) as caught:
        assert_business_only(headers, [*cells, PHONE_SHAPED])

    message = str(caught.value)
    assert PHONE_SHAPED not in message
    assert "1 cell(s)" in message


def test_a_leaky_workbook_is_never_written_to_disk(tmp_path: Path) -> None:
    """The control runs before the save, so the leaky file never exists at all.

    Writing it and then deleting it would leave a window in which real personal data sat on
    a disk that may be backed up or synchronised.
    """
    path = exports_dir(tmp_path) / "leaky.xlsx"

    with pytest.raises(PersonalDataInExportError, match="Malaysian mobile number"):
        write_queue_b_workbook(_leaky_population(), PRIORITIES, path=path, meta=META)

    assert not path.exists()


def test_the_leak_test_is_not_vacuous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With the control removed, the same leaky workbook writes successfully.

    This is what makes the test above meaningful. Without it, an `assert_business_only`
    that silently did nothing would pass every other test in this file.
    """
    monkeypatch.setattr("grid.export.xlsx.PERSONAL_DATA_PATTERNS", {})
    path = exports_dir(tmp_path) / "leaky.xlsx"

    written_path = write_queue_b_workbook(_leaky_population(), PRIORITIES, path=path, meta=META)

    assert written_path.is_file()
    book = load_workbook(written_path)
    try:
        names = [str(value) for value in _column_values(book[SHEET_QUEUE_B], "Clinic name")]
        assert any(PHONE_SHAPED in name for name in names), (
            "the fixture must really contain the leak the control is meant to catch"
        )
    finally:
        book.close()


def test_a_workbook_declared_as_holding_personal_data_says_so(tmp_path: Path) -> None:
    """When `contains_personal_data` is True the check is skipped and the cover warns.

    Per `docs/context/brand.md`, such a workbook must name its retention expectation rather
    than look identical to the business-only one.
    """
    meta = WorkbookMeta(
        title=META.title,
        as_of=META.as_of,
        generated_at=META.generated_at,
        source_note=META.source_note,
        contains_personal_data=True,
    )
    path = write_queue_b_workbook(
        _leaky_population(), PRIORITIES, path=exports_dir(tmp_path) / "contact.xlsx", meta=meta
    )

    book = load_workbook(path)
    try:
        values = [str(value) for value in _sheet_values(book[SHEET_COVER])]
        assert any(value.startswith("Yes — handle under the PMCare") for value in values)
        assert any("delete your copy" in value for value in values)
        assert BUSINESS_ONLY_NOTICE not in values
    finally:
        book.close()


# --------------------------------------------------------------------------------------
# Degenerate input
# --------------------------------------------------------------------------------------


def test_an_empty_population_still_produces_a_readable_workbook(tmp_path: Path) -> None:
    """A slow month is not a crash. Every sheet, notices and all, with no data rows."""
    empty = QueueBPopulation(report=REPORT, call_list=(), win_back=(), review=())
    path = write_queue_b_workbook(empty, {}, path=exports_dir(tmp_path) / "empty.xlsx", meta=META)

    book = load_workbook(path)
    try:
        assert book.sheetnames == list(SHEET_ORDER)
        sheet = book[SHEET_QUEUE_B]
        assert sheet.max_row == HEADER_ROW
        assert sheet.auto_filter.ref == f"A{HEADER_ROW}:S{HEADER_ROW}"

        caveat = [str(value) for value in _sheet_values(book[SHEET_NOTES])]
        assert any("No appointment date is present" in value for value in caveat)
    finally:
        book.close()


def test_headers_are_stable_across_runs(destination: Path, tmp_path: Path) -> None:
    """Two runs of the same input produce the same columns, so exports diff cleanly."""
    first = write_queue_b_workbook(POPULATION, PRIORITIES, path=destination, meta=META)
    second = write_queue_b_workbook(
        POPULATION, PRIORITIES, path=exports_dir(tmp_path) / "again.xlsx", meta=META
    )

    def headers_of(path: Path) -> Sequence[str]:
        book = load_workbook(path)
        try:
            return _harvest(book)[0]
        finally:
            book.close()

    assert headers_of(first) == headers_of(second)
