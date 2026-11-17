from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / "infrastructure" / ".env.example"


def test_missing_required_variable_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL")
    with pytest.raises(ValidationError, match="database_url"):
        Settings()


def test_signed_url_ttl_above_ten_minutes_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_SIGNED_URL_TTL_SECONDS", "601")
    with pytest.raises(ValidationError, match="600"):
        Settings()


def test_secrets_are_masked_in_repr(settings: Settings) -> None:
    text = repr(settings)
    assert "test-secret-key" not in text
    assert "test-only" not in text


def test_every_setting_is_documented_in_env_example() -> None:
    """CLAUDE.md: every variable must be listed in infrastructure/.env.example."""
    documented = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", ENV_EXAMPLE.read_text(), re.MULTILINE))
    required = {name.upper() for name in Settings.model_fields}
    assert required <= documented, f"missing from .env.example: {sorted(required - documented)}"
