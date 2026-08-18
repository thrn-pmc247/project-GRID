"""Runtime configuration via pydantic-settings.

Every field maps to a GRID_-prefixed environment variable and must be documented
in .env.example — enforced by scripts/check_context.py (check 12). Secrets live in
.env only (gitignored); never in code.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from the environment and .env."""

    model_config = SettingsConfigDict(
        env_prefix="GRID_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://grid:grid_dev_password@localhost:5432/grid"
    google_maps_api_key: str = ""
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"
    environment: str = "dev"
    # Keyed-hash secret for pseudonymising DOCTOR_NAME (PDPA 2010). Deliberately blank
    # by default — grid.pr001.pdpa raises rather than hash with an empty key, since a
    # keyless digest over a name space this small is trivially reversible.
    pii_hash_salt: str = ""
    # HARD GATE — outreach send capability. Stays False until PMCare compliance
    # sign-off (docs/context/compliance-outreach.md, CLAUDE.md guardrail 6).
    outreach_send_enabled: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
