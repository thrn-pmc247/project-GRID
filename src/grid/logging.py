"""Structured logging via structlog.

JSON renderer in prod, coloured console in dev.
Guardrail: never log PII or full raw payloads containing personal data — log
record counts and internal IDs only (docs/context/compliance-pdpa.md).
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO", environment: str = "dev") -> None:
    """Configure structlog for the whole process."""
    renderer: structlog.types.Processor
    if environment == "prod":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
        cache_logger_on_first_use=True,
    )
