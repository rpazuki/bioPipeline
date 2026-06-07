from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


AIProviderName = Literal["claude", "openai", "gemini", "openai_compatible", "fake"]

KNOWN_PROVIDERS: tuple[str, ...] = ("claude", "openai", "gemini", "openai_compatible", "fake")


@dataclass(frozen=True)
class ProviderStatus:
    provider: str
    enabled: bool
    configured: bool
    model: str
    base_url: str
    is_default: bool = False


@dataclass(frozen=True)
class ResolvedAIProviderConfig:
    provider: str
    api_key: str
    model: str
    base_url: str
    temperature: float
    max_tokens: int


def provider_statuses(ai_config: dict[str, Any]) -> list[ProviderStatus]:
    providers = (
        ai_config.get("providers", {})
        if isinstance(ai_config.get("providers"), dict)
        else {}
    )
    default_provider = str(ai_config.get("default_provider", "claude"))
    statuses: list[ProviderStatus] = []
    for provider, raw in providers.items():
        if not isinstance(raw, dict):
            continue
        statuses.append(
            ProviderStatus(
                provider=provider,
                enabled=bool(raw.get("enabled", False)),
                configured=bool(str(raw.get("api_key", "")).strip()) or provider == "fake",
                model=str(raw.get("model", "")),
                base_url=str(raw.get("base_url", "")),
                is_default=provider == default_provider,
            )
        )
    return statuses


def resolve_provider_config(
    ai_config: dict[str, Any],
    *,
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> ResolvedAIProviderConfig:
    providers = (
        ai_config.get("providers", {})
        if isinstance(ai_config.get("providers"), dict)
        else {}
    )
    provider_name = provider or str(ai_config.get("default_provider", "claude"))
    if provider_name not in providers:
        raise ValueError(f"AI provider is not configured: {provider_name}")
    raw = providers[provider_name]
    if not isinstance(raw, dict):
        raise ValueError(f"AI provider config is invalid: {provider_name}")
    if not bool(raw.get("enabled", False)):
        raise ValueError(f"AI provider is disabled: {provider_name}")
    api_key = str(raw.get("api_key", ""))
    if provider_name != "fake" and not api_key.strip():
        raise ValueError(f"AI provider is missing an API key: {provider_name}")
    resolved_model = model if model is not None else str(raw.get("model", ""))
    if provider_name != "fake" and not resolved_model.strip():
        raise ValueError(f"AI provider is missing a model: {provider_name}")
    return ResolvedAIProviderConfig(
        provider=provider_name,
        api_key=api_key,
        model=resolved_model,
        base_url=str(raw.get("base_url", "")),
        temperature=(
            temperature
            if temperature is not None
            else float(ai_config.get("temperature", 0.2))
        ),
        max_tokens=max_tokens if max_tokens is not None else int(ai_config.get("max_tokens", 4096)),
    )


def provider_test_result(ai_config: dict[str, Any], **selection: Any) -> dict[str, Any]:
    resolved = resolve_provider_config(ai_config, **selection)
    return {
        "ok": True,
        "provider": resolved.provider,
        "model": resolved.model,
        "message": (
            "Provider configuration is present. Live provider calls are planned "
            "for the provider layer."
        ),
    }


def redact_provider_error(message: str, ai_config: dict[str, Any]) -> str:
    redacted = message
    providers = (
        ai_config.get("providers", {})
        if isinstance(ai_config.get("providers"), dict)
        else {}
    )
    for raw in providers.values():
        if not isinstance(raw, dict):
            continue
        api_key = str(raw.get("api_key", ""))
        if api_key:
            redacted = redacted.replace(api_key, "[redacted]")
    return redacted
