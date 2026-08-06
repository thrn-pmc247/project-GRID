"""SQLAlchemy declarative base.

Tables are designed in docs/context/data-model.md before any migration is written.
The first revision (clinic, clinic_source_record, practitioner, recency_signal,
panel_membership, snapshot, engagement, kpi_month) is a Phase 1 task.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all GRID tables."""
