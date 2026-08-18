"""GRID command-line interface (Typer).

Orchestration entry point per ADR 0002 (APScheduler + CLI, not Prefect).

The PR001 and Queue B commands run **offline against SQLite** by default. Docker Desktop
is not installed (open question 2), and `grid.db.engine.make_engine` attaches one
`<schema>.sqlite` file per layer schema, so a full five-schema database lives inside the
gitignored `data/` directory with no server. That is what makes Queue B deliverable today
rather than after a Postgres install (ADR 0006).
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import Engine

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


DEFAULT_OFFLINE_URL = "sqlite+pysqlite:///data/grid/grid.sqlite"
"""Offline default. `data/` is gitignored entirely, so no clinic data reaches git."""


DbUrl = Annotated[str | None, typer.Option(help="SQLAlchemy URL. Defaults to offline SQLite.")]
AsOf = Annotated[str | None, typer.Option(help="Evaluate activity as at this date (YYYY-MM-DD).")]
States = Annotated[list[str] | None, typer.Option("--state", help="Restrict to these state codes.")]


def _engine(database_url: str | None) -> Engine:
    """Build an engine with the layer schemas attached."""
    from grid.db.engine import make_engine

    return make_engine(database_url or DEFAULT_OFFLINE_URL)


@app.command("load-pr001")
def load_pr001(
    path: Annotated[Path, typer.Argument(help="Path to the PR001 parquet extract.")],
    database_url: DbUrl = None,
    today: Annotated[
        str | None, typer.Option(help="Reference date (YYYY-MM-DD) for PII retention.")
    ] = None,
    create_tables: Annotated[
        bool, typer.Option(help="Create tables if absent (SQLite offline path).")
    ] = True,
) -> None:
    """Load a PR001 extract through bronze, staging, core and pii.

    Reloading the same file is a no-op — bronze is idempotent on the file's SHA-256.
    """
    from grid.pr001.pdpa import MissingSaltError, get_salt
    from grid.pr001.pipeline import create_all, run_pr001_pipeline

    if not path.is_file():
        typer.echo(f"Extract not found: {path}", err=True)
        raise typer.Exit(code=2)
    try:
        salt = get_salt()
    except MissingSaltError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    engine = _engine(database_url)
    if create_tables:
        create_all(engine)
    report = run_pr001_pipeline(
        engine,
        path,
        salt=salt,
        today=dt.date.fromisoformat(today) if today else None,
    )
    typer.echo(f"bronze   {report.bronze.row_count:>7,} rows x {report.bronze.column_count} cols")
    typer.echo(f"staging  {report.staging.rows_out:>7,}")
    typer.echo(f"core     {report.core.outlets:>7,}")
    typer.echo(f"pii      {report.pii_rows:>7,}")
    typer.echo(f"reconciles: {report.reconciles}")
    if not report.reconciles:
        raise typer.Exit(code=1)


@app.command("queue-b")
def queue_b(
    as_of: AsOf = None,
    state: States = None,
    database_url: DbUrl = None,
) -> None:
    """Print the Queue B suppression funnel. Business columns only — never a phone number."""
    from grid.panel.suppression import queue_b_population

    reference = dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    population = queue_b_population(
        _engine(database_url),
        as_of=reference,
        states=state or None,
    )
    r = population.report
    typer.echo(f"Queue B as at {r.as_of}")
    typer.echo(f"  GP rows                      {r.gp_rows:>7,}")
    typer.echo(f"  active (point-in-time)       {r.gp_active_as_of:>7,}")
    typer.echo(f"  active (status_code='A')     {r.gp_active_status_code_a:>7,}")
    typer.echo(f"    definitions disagree on    {r.status_code_disagreements:>7,}")
    typer.echo(f"  on panel                     {r.on_panel:>7,}")
    typer.echo(f"  NOT on panel                 {r.not_on_panel:>7,}")
    typer.echo(f"    excluded, superseded       {r.excluded_superseded:>7,}")
    typer.echo(f"    routed, flagged            {r.routed_to_review_flagged:>7,}")
    typer.echo(f"    routed, likely on panel    {r.routed_to_review_likely_on_panel:>7,}")
    typer.echo(f"  CALL LIST                    {r.queue_b_final:>7,}")
    typer.echo(f"  win-back                     {r.win_back:>7,}")
    typer.echo(f"  reconciles: {r.reconciles}")
    if not r.reconciles:
        raise typer.Exit(code=1)


@app.command("export-queue-b")
def export_queue_b(
    as_of: AsOf = None,
    out: Annotated[
        Path | None, typer.Option(help="Output path. Defaults to data/exports/.")
    ] = None,
    state: States = None,
    database_url: DbUrl = None,
) -> None:
    """Write the branded Queue B workbook.

    The workbook carries **no phone numbers**: it is business data throughout, so it
    ships without waiting on the outstanding personal-data questions. A contact workbook
    is a separate, gated artefact.
    """
    from grid.export.xlsx import WorkbookMeta, exports_dir, write_queue_b_workbook
    from grid.panel.contactability import contactability
    from grid.panel.suppression import queue_b_population
    from grid.score.priority import rank

    reference = dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    engine = _engine(database_url)
    population = queue_b_population(engine, as_of=reference, states=state or None)
    phones, summary = contactability(engine)
    ranked = rank(population.call_list, phones, as_of=reference)
    priorities = {row.provider_code: priority for row, priority in ranked}

    destination = out or (exports_dir() / f"queue-b-{reference.isoformat()}.xlsx")
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = write_queue_b_workbook(
        population,
        priorities,
        path=destination,
        meta=WorkbookMeta(
            title="Queue B — GP clinics not on the PMCare panel",
            as_of=reference,
            generated_at=dt.datetime.now(),
            source_note=(
                f"Derived from the PMCare provider master. "
                f"{population.report.queue_b_final:,} callable rows of "
                f"{population.report.not_on_panel:,} not on panel."
            ),
            contains_personal_data=False,
        ),
    )
    typer.echo(f"wrote {written}")
    typer.echo(
        f"  {len(population.call_list):,} call list · {len(population.win_back):,} win-back "
        f"· {len(population.review):,} review"
    )
    typer.echo(
        f"  contactable {summary.contactable:,} · mobile-only excluded {summary.mobile_only:,}"
    )


@app.command("check-context")
def check_context() -> None:
    """Run the context hygiene gate (scripts/check_context.py)."""
    script = _REPO_ROOT / "scripts" / "check_context.py"
    if not script.is_file():
        typer.echo("scripts/check_context.py not found — run from a repo checkout.", err=True)
        raise typer.Exit(code=1)
    result = subprocess.run([sys.executable, str(script)], check=False)
    raise typer.Exit(code=result.returncode)
