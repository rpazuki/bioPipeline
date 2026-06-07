from __future__ import annotations

from app.core.config import _resolve_ai_secrets


def test_resolve_ai_secrets_expands_placeholder(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-123")
    ai = {"providers": {"claude": {"api_key": "${ANTHROPIC_API_KEY}"}}}
    resolved = _resolve_ai_secrets(ai)
    assert resolved["providers"]["claude"]["api_key"] == "env-key-123"


def test_resolve_ai_secrets_blank_falls_back_to_convention(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-env")
    ai = {"providers": {"openai": {"api_key": ""}}}
    resolved = _resolve_ai_secrets(ai)
    assert resolved["providers"]["openai"]["api_key"] == "openai-env"


def test_resolve_ai_secrets_explicit_api_key_env(monkeypatch):
    monkeypatch.setenv("MY_CUSTOM_KEY", "custom-123")
    ai = {"providers": {"gemini": {"api_key": "", "api_key_env": "MY_CUSTOM_KEY"}}}
    resolved = _resolve_ai_secrets(ai)
    assert resolved["providers"]["gemini"]["api_key"] == "custom-123"


def test_resolve_ai_secrets_missing_env_stays_blank(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    ai = {"providers": {"gemini": {"api_key": ""}}}
    resolved = _resolve_ai_secrets(ai)
    assert resolved["providers"]["gemini"]["api_key"] == ""
