"""Database engine and session factories."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from grid.config import get_settings


def make_engine(echo: bool = False) -> Engine:
    """Create an engine from settings (GRID_DATABASE_URL)."""
    return create_engine(get_settings().database_url, echo=echo)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Provide a transactional scope for a unit of work."""
    factory = sessionmaker(bind=engine if engine is not None else make_engine())
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
