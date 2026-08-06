"""GRID command-line interface (Typer).

Orchestration entry point per ADR 0002 (APScheduler + CLI, not Prefect).
Pipeline commands (ckaps ingest, diff, export, …) land in Phase 1.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

from grid import __version__
from grid.config import get_settings
from grid.logging import configure_logging

app = typer.Typer(
    help="GRID — GP Registry & Intelligence Database (PMCare PNM discovery pipeline).",
    no_args_is_help=True,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


@app.callback()
def _init() -> None:
    """Configure logging before any command runs."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.environment)


@app.command()
def version() -> None:
    """Print the GRID version."""
    typer.echo(f"grid {__version__}")


@app.command("check-context")
def check_context() -> None:
    """Run the context hygiene gate (scripts/check_context.py)."""
    script = _REPO_ROOT / "scripts" / "check_context.py"
    if not script.is_file():
        typer.echo("scripts/check_context.py not found — run from a repo checkout.", err=True)
        raise typer.Exit(code=1)
    result = subprocess.run([sys.executable, str(script)], check=False)
    raise typer.Exit(code=result.returncode)
