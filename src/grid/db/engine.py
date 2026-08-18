"""Engine construction for GRID's layered schema model.

The layer model uses real SQL schemas — `bronze`, `staging`, `core`, `ops`, `pii` — so
that the boundary between "what the source said" and "what we concluded" is enforced by
the database rather than by a naming convention.

Postgres is the production target. Open question 2 records that Docker Desktop is not
installed on the build machine, and the PR001 work is specified as offline-buildable, so
the same DDL must also run on SQLite. SQLite has no `CREATE SCHEMA`, but `ATTACH
DATABASE` provides genuine schema-qualified names (`bronze.pr001_provider_master`), which
is enough to keep one set of table definitions for both engines. See ADR 0006.

Accepted limitation: SQLite does not exercise PostGIS, so geometry is not validated
offline. This is why the coordinate gate stores plain float columns plus a quality enum
rather than a PostGIS point — see `grid.normalise.coordinates`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

SCHEMAS: Final[tuple[str, ...]] = ("bronze", "staging", "core", "ops", "pii")
"""The layer schemas, in dependency order.

* `bronze` — source landing, verbatim, append-only generations.
* `staging` — typed, cleaned, one row per bronze row of the current generation.
* `core` — the modelled network, plus discovery candidates and resolution edges.
* `ops` — load and transform logs.
* `pii` — personal data under PDPA 2010, segregated at schema level (guardrail 4).
"""

IN_MEMORY_URL: Final = "sqlite+pysqlite:///:memory:"


def _attach_sqlite_schemas(dbapi_connection: Any, _record: Any) -> None:
    """Attach one database per layer schema so schema-qualified names resolve.

    In-memory attachments are per-connection, which is why `make_engine` pins a
    `StaticPool` for in-memory URLs — otherwise each checkout would get a fresh,
    unattached connection.

    Args:
        dbapi_connection: The raw DBAPI connection SQLAlchemy just opened.
        _record: The pool's connection record. Unused.
    """
    cursor = dbapi_connection.cursor()
    try:
        for schema in SCHEMAS:
            cursor.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
    finally:
        cursor.close()


def _attach_sqlite_file_schemas(directory: Path) -> Callable[[Any, Any], None]:
    """Build a connect listener attaching one sibling file per schema.

    Args:
        directory: Directory holding the sibling `<schema>.sqlite` files.

    Returns:
        A listener matching SQLAlchemy's `connect` event signature
        `(dbapi_connection, connection_record) -> None`. The parameters are `Any`
        because the DBAPI connection and the pool's `_ConnectionRecord` are both
        untyped at the event boundary.
    """

    def listener(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            for schema in SCHEMAS:
                path = (directory / f"{schema}.sqlite").as_posix()
                cursor.execute(f"ATTACH DATABASE '{path}' AS {schema}")
        finally:
            cursor.close()

    return listener


def make_engine(url: str = IN_MEMORY_URL, *, echo: bool = False) -> Engine:
    """Create an engine with every layer schema available.

    Args:
        url: SQLAlchemy URL. Defaults to in-memory SQLite for tests and offline work.
        echo: Emit SQL to the logger. Never enable in production — bronze rows carry
            personal data and SQLAlchemy's echo would log it (see conventions.md:
            never log PII or full raw payloads).

    Returns:
        An engine on which `bronze.`, `staging.`, `core.`, `ops.` and `pii.` resolve.
    """
    if url.startswith("sqlite"):
        in_memory = ":memory:" in url
        engine = create_engine(
            url,
            echo=echo,
            future=True,
            **(
                {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
                if in_memory
                else {}
            ),
        )
        if in_memory:
            event.listen(engine, "connect", _attach_sqlite_schemas)
        else:
            directory = Path(engine.url.database or ".").resolve().parent
            directory.mkdir(parents=True, exist_ok=True)
            event.listen(engine, "connect", _attach_sqlite_file_schemas(directory))
        return engine

    engine = create_engine(url, echo=echo, future=True)
    ensure_schemas(engine)
    return engine


def ensure_schemas(engine: Engine) -> None:
    """Create the layer schemas on a Postgres engine. A no-op on SQLite (ATTACH does it)."""
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        for schema in SCHEMAS:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a session factory bound to `engine`."""
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


@contextmanager
def begin(engine: Engine) -> Iterator[Connection]:
    """Yield a transactional connection, committing on success."""
    with engine.begin() as conn:
        yield conn
