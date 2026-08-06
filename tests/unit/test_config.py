"""Guardrail tests on runtime configuration."""

from __future__ import annotations

from grid.config import Settings


def test_outreach_send_disabled_by_default() -> None:
    """CLAUDE.md guardrail 6: send capability defaults off, pending compliance sign-off."""
    settings = Settings(_env_file=None)
    assert settings.outreach_send_enabled is False


def test_env_prefix_is_grid() -> None:
    assert Settings.model_config.get("env_prefix") == "GRID_"
