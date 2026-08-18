"""Shared pytest configuration.

Fixture policy: synthetic data only — never real clinic data, PII or credentials
(CLAUDE.md guardrail 5, docs/context/conventions.md).

The PR001 fixtures below build a **synthetic** parquet extract carrying all 70 columns of
`grid.pr001.columns.SOURCE_COLUMNS`, in the contract's order and with the dtype each
`ColumnSpec.logical_type` implies. Every value is fabricated and recognisably fake
(`KLINIK CONTOH SATU`, `Dr Demo Satu`, `+60300000001`), following the style of
`scripts/seed_synthetic.py`. `PR001.parquet` itself is gitignored and absent in CI, so
nothing here may depend on it.

The twelve rows are crafted to exercise the edge cases the pipeline exists to handle —
the coordinate gate's six verdicts, the `1900-01-01` sentinel, a future-dated
termination, a shared chain base name, a case-folded staff identity, an invalid postcode
— with every classification code drawn only from the vocabularies declared in
`grid.pr001.reference`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final

import polars as pl
import pytest
from sqlalchemy import Engine

from grid.db.engine import make_engine
from grid.pr001.columns import SOURCE_COLUMN_SPECS, SOURCE_COLUMNS, LogicalType
from grid.pr001.pipeline import PipelineReport, create_all, run_pr001_pipeline
from grid.pr001.staging import DEFAULT_THRESHOLDS

SYNTHETIC_SALT: Final = "grid-test-salt-not-a-secret"
"""HMAC key for the synthetic fixtures. Never a real salt — the real one lives only in
`.env` (gitignored) as `GRID_PII_HASH_SALT`."""

SYNTHETIC_TODAY: Final = dt.date(2026, 8, 17)
"""Reference date, pinned so retention and point-in-time assertions are deterministic."""

SYNTHETIC_INGESTED_AT: Final = dt.datetime(2026, 8, 17, 9, 0, 0)

SYNTHETIC_ROW_COUNT: Final = 12

_POLARS_DTYPE_FOR: Final[Mapping[LogicalType, pl.DataType]] = {
    LogicalType.STRING: pl.String(),
    LogicalType.BOOLEAN: pl.Boolean(),
    LogicalType.INT64: pl.Int64(),
    LogicalType.DOUBLE: pl.Float64(),
    LogicalType.TIMESTAMP_MICROS: pl.Datetime("us"),
    LogicalType.TIME_NANOS: pl.Time(),
}
"""Parquet dtype per logical type, so the fixture round-trips to the same logical types
the profiler recorded for the real extract."""

SYNTHETIC_SCHEMA: Final[Mapping[str, pl.DataType]] = {
    spec.name: _POLARS_DTYPE_FOR[spec.logical_type] for spec in SOURCE_COLUMN_SPECS
}
"""Ordered schema: exactly `SOURCE_COLUMNS`, in the contract's physical order."""

# --------------------------------------------------------------------------------------
# The twelve synthetic rows
# --------------------------------------------------------------------------------------

CHAIN_BASE_NAME: Final = "KLINIK CONTOH TUJUH"
"""The base name rows 6 and 7 share once the corporate suffix and branch qualifier are
stripped — the fixture's one inferred chain."""

CASE_FOLDED_USER: Final = "m_noor"
"""Rows 8 and 9 carry `M_NOOR` and `m_noor`; both fold onto this canonical identity."""

INVALID_POSTCODE: Final = "814000"
"""Six digits. Never truncated to `81400` — that would relocate the clinic."""

FUTURE_TERMINATION_DATE: Final = dt.datetime(2028, 1, 15)
"""Later than `SYNTHETIC_TODAY`, so `STATUS_CODE='T'` does not mean "inactive today"."""

SENTINEL_DATE: Final = dt.datetime(1900, 1, 1)
"""`ACC_VENDOR_FLAG_DATE`'s "not set" sentinel. Staging remaps it to NULL."""

VALID_COORDINATES: Final = (3.123400, 101.654300)
REPAIRABLE_COORDINATES: Final = (3.112491, 101591143.0)
"""Longitude inflated by 10^6. Exactly one power of ten rescales it into range, so the
gate repairs it as REPAIRED_DECIMAL."""

OUT_OF_BOUNDS_COORDINATES: Final = (88.8888, 188.8888)
"""Repdigits well outside both axis ranges and not unambiguously repairable."""

_SYNTHETIC_ROWS: Final[tuple[dict[str, Any], ...]] = (
    # 0 — the clean baseline row: valid coordinates, real operating hours, on panel.
    {
        "PROVIDER_CODE": "GRIDGP0001",
        "PROVIDER_DESCRIPTION": "KLINIK CONTOH SATU",
        "PROVIDER_TYPE_CODE": "GP",
        "STATE_CODE": "SL",
        "STATUS_CODE": "A",
        "CATEGORY_CODE": "P",
        "PAYMENT_METHOD_CODE": "C",
        "OWNERSHIP_CODE": "0",
        "id_LK180": 0,
        "PMCARE_PANEL_STATUS": True,
        "ADDRESS1": "NO. 1, JALAN CONTOH 1/1",
        "ADDRESS2": "TAMAN CONTOH",
        "CITY": "SHAH ALAM CONTOH",
        "POSTCODE": "40000",
        "LATITUDE": VALID_COORDINATES[0],
        "LONGITUDE": VALID_COORDINATES[1],
        "APPOINMENT_DATE": dt.datetime(2026, 1, 15),
        "DOCTOR_NAME": "Dr Demo Satu",
        "GENERAL_PHONE_NO": "+60300000001",
        "STANDARD_HOUR_FROM": dt.time(8, 30),
        "STANDARD_HOUR_TO": dt.time(17, 0),
        "PUBLIC_HOUR_FROM": dt.time(9, 0),
        "PUBLIC_HOUR_TO": dt.time(13, 0),
        "CREATE_BY": "DEMO_ONE",
        "einv_email": "demo.satu@contoh.invalid",
    },
    # 1 — Null Island: the upstream imputation bug, never a location.
    {
        "PROVIDER_CODE": "GRIDGP0002",
        "PROVIDER_DESCRIPTION": "KLINIK CONTOH DUA",
        "PROVIDER_TYPE_CODE": "GP",
        "STATE_CODE": "KL",
        "STATUS_CODE": "A",
        "CATEGORY_CODE": "P",
        "PAYMENT_METHOD_CODE": "M",
        "PMCARE_PANEL_STATUS": True,
        "ADDRESS1": "LOT 2, TINGKAT BAWAH, JALAN CONTOH 2",
        "CITY": "KUALA CONTOH",
        "POSTCODE": "50450",
        "LATITUDE": 0.0,
        "LONGITUDE": 0.0,
        "APPOINMENT_DATE": dt.datetime(2026, 2, 20),
        "REMARKS": "KLINIK CONTOH CLOSED SINCE 2026",
        "DOCTOR_NAME": "Dr Demo Dua",
        "GENERAL_PHONE_NO": "+60300000002",
    },
    # 2 — coordinates absent altogether; also the out-of-scope dental discipline.
    {
        "PROVIDER_CODE": "GRIDDT0003",
        "PROVIDER_DESCRIPTION": "KLINIK PERGIGIAN CONTOH TIGA",
        "PROVIDER_TYPE_CODE": "DT",
        "STATE_CODE": "JB",
        "STATUS_CODE": "A",
        "CATEGORY_CODE": "P",
        "PAYMENT_METHOD_CODE": "C",
        "PMCARE_PANEL_STATUS": False,
        "ADDRESS1": "NO. 3, PERSIARAN CONTOH",
        "CITY": "JOHOR CONTOH",
        "POSTCODE": "80000",
        "APPOINMENT_DATE": dt.datetime(2026, 3, 10),
    },
    # 3 — longitude inflated by a factor of a million: repairable by decimal shift.
    {
        "PROVIDER_CODE": "GRIDGP0004",
        "PROVIDER_DESCRIPTION": "KLINIK CONTOH EMPAT",
        "PROVIDER_TYPE_CODE": "GP",
        "STATE_CODE": "PG",
        "STATUS_CODE": "A",
        "CATEGORY_CODE": "P",
        "PAYMENT_METHOD_CODE": "C",
        "PMCARE_PANEL_STATUS": True,
        "ADDRESS1": "NO. 4, LORONG CONTOH",
        "CITY": "PULAU CONTOH",
        "POSTCODE": "10450",
        "LATITUDE": REPAIRABLE_COORDINATES[0],
        "LONGITUDE": REPAIRABLE_COORDINATES[1],
        "APPOINMENT_DATE": dt.datetime(2026, 4, 5),
        "DOCTOR_NAME": "Dr Demo Empat",
    },
    # 4 — out of bounds beyond repair, plus the 1900-01-01 "not set" sentinel.
    {
        "PROVIDER_CODE": "GRIDOP0005",
        "PROVIDER_DESCRIPTION": "OPTIK CONTOH LIMA",
        "PROVIDER_TYPE_CODE": "OP",
        "STATE_CODE": "SB",
        "STATUS_CODE": "A",
        "CATEGORY_CODE": "G",
        "PAYMENT_METHOD_CODE": "X",
        "OWNERSHIP_CODE": "1",
        "id_LK180": 1,
        "PMCARE_PANEL_STATUS": False,
        "ADDRESS1": "LOT 5, BLOK B, JALAN CONTOH 5",
        "CITY": "KOTA CONTOH",
        "POSTCODE": "88000",
        "LATITUDE": OUT_OF_BOUNDS_COORDINATES[0],
        "LONGITUDE": OUT_OF_BOUNDS_COORDINATES[1],
        "APPOINMENT_DATE": dt.datetime(2025, 5, 5),
        "ACC_VENDOR_FLAG_DATE": SENTINEL_DATE,
        "ACC_VENDOR_FLAG": True,
    },
    # 5 — terminated on paper, but not until 2028: the point-in-time trap.
    {
        "PROVIDER_CODE": "GRIDGP0006",
        "PROVIDER_DESCRIPTION": "KLINIK CONTOH ENAM",
        "PROVIDER_TYPE_CODE": "GP",
        "STATE_CODE": "SR",
        "STATUS_CODE": "T",
        "CATEGORY_CODE": "P",
        "PAYMENT_METHOD_CODE": "M",
        "PMCARE_PANEL_STATUS": False,
        "ADDRESS1": "NO. 6, JALAN CONTOH 6",
        "CITY": "KUCHING CONTOH",
        "POSTCODE": "93000",
        "APPOINMENT_DATE": dt.datetime(2020, 6, 1),
        "TERMINATION_DATE": FUTURE_TERMINATION_DATE,
        "REMARKS": "FILE 01/02/2026 CONTOH",
    },
    # 6 — chain outlet, corporate suffix form.
    {
        "PROVIDER_CODE": "GRIDGP0007",
        "PROVIDER_DESCRIPTION": "KLINIK CONTOH TUJUH SDN BHD",
        "PROVIDER_TYPE_CODE": "GP",
        "STATE_CODE": "SL",
        "STATUS_CODE": "A",
        "CATEGORY_CODE": "P",
        "PAYMENT_METHOD_CODE": "C",
        "OWNERSHIP_CODE": "2",
        "id_LK180": 2,
        "PMCARE_PANEL_STATUS": True,
        "ADDRESS1": "NO. 7, JALAN CONTOH 7",
        "CITY": "PETALING CONTOH",
        "POSTCODE": "40100",
        "APPOINMENT_DATE": dt.datetime(2026, 5, 11),
    },
    # 7 — the same chain, branch-qualifier form. Shares row 6's chain base name.
    {
        "PROVIDER_CODE": "GRIDGP0008",
        "PROVIDER_DESCRIPTION": "KLINIK CONTOH TUJUH (TMN CONTOH)",
        "PROVIDER_TYPE_CODE": "GP",
        "STATE_CODE": "SL",
        "STATUS_CODE": "A",
        "CATEGORY_CODE": "P",
        "PAYMENT_METHOD_CODE": "C",
        "OWNERSHIP_CODE": "2",
        "id_LK180": 2,
        "PMCARE_PANEL_STATUS": True,
        "ADDRESS1": "NO. 8, JALAN CONTOH 8",
        "CITY": "PETALING CONTOH",
        "POSTCODE": "40150",
        "APPOINMENT_DATE": dt.datetime(2026, 6, 12),
    },
    # 8 — staff identity in upper case.
    {
        "PROVIDER_CODE": "GRIDPH0009",
        "PROVIDER_DESCRIPTION": "FARMASI CONTOH LAPAN",
        "PROVIDER_TYPE_CODE": "PH",
        "STATE_CODE": "KD",
        "STATUS_CODE": "A",
        "CATEGORY_CODE": "P",
        "PAYMENT_METHOD_CODE": "M",
        "PMCARE_PANEL_STATUS": False,
        "ADDRESS1": "NO. 9, JALAN CONTOH 9",
        "CITY": "ALOR CONTOH",
        "POSTCODE": "05000",
        "APPOINMENT_DATE": dt.datetime(2026, 7, 1),
        "STATUS_BY": "M_NOOR",
        "CREATE_BY": "M_NOOR",
        "GL_ELIGIBILITY_APPROVE_BY": "M_NOOR",
        "GL_ELIGIBILITY_STATUS": True,
    },
    # 9 — the same person keyed in lower case, plus a suspension.
    {
        "PROVIDER_CODE": "GRIDSP0010",
        "PROVIDER_DESCRIPTION": "KLINIK PAKAR CONTOH SEMBILAN",
        "PROVIDER_TYPE_CODE": "SP",
        "STATE_CODE": "NS",
        "STATUS_CODE": "S",
        "CATEGORY_CODE": "P",
        "PAYMENT_METHOD_CODE": "C",
        "OWNERSHIP_CODE": "3",
        "id_LK180": 3,
        "PMCARE_PANEL_STATUS": False,
        "ADDRESS1": "NO. 10, JALAN CONTOH 10",
        "CITY": "SEREMBAN CONTOH",
        "POSTCODE": "70000",
        "APPOINMENT_DATE": dt.datetime(2019, 2, 2),
        "SUSPENSION_DATE": dt.datetime(2026, 1, 5),
        "MODIFY_BY": "m_noor",
        "MODIFY_DATE": dt.datetime(2026, 1, 5, 10, 30),
    },
    # 10 — six-digit postcode. Rejected outright, never truncated.
    {
        "PROVIDER_CODE": "GRIDGP0011",
        "PROVIDER_DESCRIPTION": "KLINIK CONTOH SEPULUH",
        "PROVIDER_TYPE_CODE": "GP",
        "STATE_CODE": "PR",
        "STATUS_CODE": "A",
        "CATEGORY_CODE": "P",
        "PAYMENT_METHOD_CODE": "C",
        "PMCARE_PANEL_STATUS": True,
        "ADDRESS1": "NO. 11, JALAN CONTOH 11",
        "CITY": "IPOH CONTOH",
        "POSTCODE": INVALID_POSTCODE,
        "APPOINMENT_DATE": dt.datetime(2026, 8, 1),
        "WEBSITE": "MS. DEMO CONTOH",
    },
    # 11 — the undeclared-meaning codes: STATUS_CODE 'V', STATE_CODE 'ZZ', CATEGORY 'X'.
    {
        "PROVIDER_CODE": "GRIDGP0012",
        "PROVIDER_DESCRIPTION": "KLINIK CONTOH SEBELAS",
        "PROVIDER_TYPE_CODE": "GP",
        "STATE_CODE": "ZZ",
        "STATUS_CODE": "V",
        "CATEGORY_CODE": "X",
        "PAYMENT_METHOD_CODE": "X",
        "PMCARE_PANEL_STATUS": False,
        "ADDRESS1": "NO. 12, JALAN CONTOH 12",
        "POSTCODE": "",
        "APPOINMENT_DATE": dt.datetime(2018, 3, 3),
        "REMARKS": "DUPLICATE OF CONTOH RECORD",
        "SYS_ADMIN_REMARKS": "DEMO NOTE — SYNTHETIC ONLY",
    },
)

_ROW_DEFAULTS: Final[Mapping[str, Any]] = {
    # Verbatim source quirks every real row carries, restated once rather than twelve
    # times. `PROVIDER_ALIAS_CODE`, `SYS_ISACTIVE` and `is_TwoStagesVerify` are the
    # zero-information columns staging drops.
    "PROVIDER_ALIAS_CODE": "NONE",
    "SYS_ISACTIVE": True,
    "is_TwoStagesVerify": False,
    "MEDILINE_USER": False,
    "OPEN24HOURS": False,
    "OPEN_PUBLIC_HOLIDAYS": False,
    "GL_ELIGIBILITY_STATUS": False,
    "ACC_VENDOR_FLAG": False,
    "isPMRused": False,
    "isAME": False,
    "IsAME_MPM": False,
    "isLTM": False,
    "IsEfarma": False,
    "isPERKESO": False,
    "isOH": False,
    "NO_DOCTOR_MALE": False,
    "NO_DOCTOR_FEMALE": False,
    "PMCARE_PANEL_STATUS": False,
}


def _synthetic_row(ordinal: int, row: Mapping[str, Any]) -> dict[str, Any]:
    """Expand one crafted row to the full 70-column contract.

    Args:
        ordinal: The row's position in the fixture, used to derive its GUID.
        row: The crafted subset of columns.

    Returns:
        Every column in `SOURCE_COLUMNS`, unstated ones filled from `_ROW_DEFAULTS`
        or left NULL.
    """
    stamp = dt.datetime(2026, 8, 5, 12, 0, 0) + dt.timedelta(minutes=ordinal)
    complete: dict[str, Any] = dict.fromkeys(SOURCE_COLUMNS)
    complete.update(_ROW_DEFAULTS)
    complete.update(
        {
            "ROW_GUID": f"00000000-0000-4000-8000-{ordinal:012d}",
            # Rows 10 and 11 share one MIX_ROW_ID, mirroring the source's 15 collisions.
            # It is not a key and carries no constraint.
            "MIX_ROW_ID": 16_170 + min(ordinal, 10),
            "STATUS_DATE": stamp,
            "CREATE_DATE": stamp,
            "SYS_TIME_STAMP": stamp,
            "QR_ENCRYPTED_TEXT": f"QRDEMOPAYLOAD{ordinal:04d}",
            "QR_FILE_PATH": rf"\\CONTOH-SERVER\LineDoc\demo{ordinal:04d}.png",
        }
    )
    complete.update(row)
    return complete


def build_synthetic_frame() -> pl.DataFrame:
    """Build the synthetic PR001 extract as a polars frame.

    Returns:
        A `SYNTHETIC_ROW_COUNT`-row frame whose columns are exactly `SOURCE_COLUMNS`,
        in the contract's physical order and with the contract's dtypes.
    """
    rows = [_synthetic_row(ordinal, row) for ordinal, row in enumerate(_SYNTHETIC_ROWS)]
    columnar = {name: [row[name] for row in rows] for name in SOURCE_COLUMNS}
    frame = pl.DataFrame(columnar, schema=dict(SYNTHETIC_SCHEMA))
    assert tuple(frame.columns) == SOURCE_COLUMNS, "fixture must match the column contract"
    return frame


@pytest.fixture
def synthetic_frame() -> pl.DataFrame:
    """The synthetic extract in memory, for tests that never touch the filesystem."""
    return build_synthetic_frame()


@pytest.fixture
def synthetic_parquet(tmp_path: Path) -> Path:
    """Write the synthetic extract to a parquet file under `tmp_path`.

    Returns:
        Path to a 12-row, 70-column parquet the bronze loader accepts.
    """
    path = tmp_path / "PR001_synthetic.parquet"
    build_synthetic_frame().write_parquet(path)
    return path


@pytest.fixture
def engine() -> Iterator[Engine]:
    """An in-memory engine with every layer schema attached and every table created."""
    eng = make_engine()
    create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def synthetic_calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recalibrate the two guards that are sized for the real 33,643-row extract.

    Both guards are deliberately fatal in production and must not be weakened there;
    they are simply mis-scaled against a twelve-row fixture:

    * `EXPECTED_ROW_COUNT` is the shrinkage baseline. Any synthetic extract is smaller
      than the real one, so without this every load would raise `SourceShrinkageError`.
    * `coordinate_repair` allows a 1% repair rate — a rate that says "the repair rule has
      gone loose". The fixture holds exactly one repairable row out of twelve *by design*,
      so a share threshold carries no signal at this size.

    Every other threshold is left at its production value, so a transform that really
    does run away still breaks the test.
    """
    monkeypatch.setattr("grid.pr001.bronze.EXPECTED_ROW_COUNT", SYNTHETIC_ROW_COUNT)
    monkeypatch.setattr(
        "grid.pr001.staging.DEFAULT_THRESHOLDS",
        {**DEFAULT_THRESHOLDS, "coordinate_repair": 1.00},
    )


@pytest.fixture
def synthetic_salt() -> str:
    """The fixtures' HMAC key. Exposed as a fixture so no test imports from `conftest`."""
    return SYNTHETIC_SALT


@pytest.fixture
def synthetic_today() -> dt.date:
    """The pinned reference date for retention and point-in-time assertions."""
    return SYNTHETIC_TODAY


@pytest.fixture
def pipeline_report(
    engine: Engine, synthetic_parquet: Path, synthetic_calibration: None
) -> PipelineReport:
    """Run the whole PR001 path over the synthetic extract.

    Shared by the PDPA and integration tests: both need a fully built database, and
    building it once per test keeps each one independent of the others' mutations.

    Returns:
        The report for the run. The database is the `engine` fixture's, so a test can take
        both and query the layers directly.
    """
    return run_pr001_pipeline(
        engine,
        synthetic_parquet,
        salt=SYNTHETIC_SALT,
        today=SYNTHETIC_TODAY,
        ingested_at=SYNTHETIC_INGESTED_AT,
    )
