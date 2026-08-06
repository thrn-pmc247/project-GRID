"""Asserts the context hygiene gate passes, so plain `pytest` catches doc drift."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_check_context_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_context.py")],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert result.returncode == 0, "check_context.py failed:\n" + result.stdout + result.stderr
