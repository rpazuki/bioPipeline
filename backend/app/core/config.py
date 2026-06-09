from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_THIS_FILE = Path(__file__).resolve()
_BACKEND_DIR = _THIS_FILE.parents[2]
_REPO_ROOT = _THIS_FILE.parents[3]
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "configs" / "app_config.yaml"

# Load .env into the process environment before reading the YAML config, so
# secrets such as provider API keys can be referenced as ${VAR} placeholders.
for _env_path in (_REPO_ROOT / ".env", _BACKEND_DIR / ".env"):
    if _env_path.exists():
        load_dotenv(_env_path, override=False)

_ENV_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")

# Fallback environment variable names when a provider's api_key is left blank.
_DEFAULT_AI_KEY_ENV = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai_compatible": "OPENAI_COMPATIBLE_API_KEY",
}


def _expand_env(value: str) -> str:
    return _ENV_PLACEHOLDER.sub(lambda match: os.environ.get(match.group(1), ""), value)


def _resolve_ai_secrets(ai: Any) -> Any:
    """Fill provider api_key/base_url from the environment.

    Supports ``${VAR}`` placeholders, an explicit ``api_key_env`` field, and a
    conventional per-provider env var when the key is left blank. Keys are read
    server-side only and are never echoed back to the frontend.
    """
    if not isinstance(ai, dict):
        return ai
    providers = ai.get("providers")
    if not isinstance(providers, dict):
        return ai
    for name, raw in providers.items():
        if not isinstance(raw, dict):
            continue
        api_key = str(raw.get("api_key", ""))
        if "${" in api_key:
            api_key = _expand_env(api_key)
        if not api_key.strip():
            env_name = str(raw.get("api_key_env", "")) or _DEFAULT_AI_KEY_ENV.get(name, "")
            if env_name:
                api_key = os.environ.get(env_name, "")
        raw["api_key"] = api_key
        base_url = raw.get("base_url")
        if isinstance(base_url, str) and "${" in base_url:
            raw["base_url"] = _expand_env(base_url)
    return ai


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _resolve_environment(doc: dict[str, Any]) -> str:
    default_env = (
        str(doc.get("defaults", {}).get("environment", "development"))
        if isinstance(doc.get("defaults"), dict)
        else "development"
    )
    return default_env.lower()


def load_backend_config() -> dict[str, Any]:
    config_path = Path(os.environ.get("APP_CONFIG_PATH", str(_DEFAULT_CONFIG_PATH))).expanduser()
    doc = _load_yaml_config(config_path)
    backend = doc.get("backend", {}) if isinstance(doc.get("backend"), dict) else {}
    shared = backend.get("shared", {}) if isinstance(backend.get("shared"), dict) else {}

    requested_env = os.environ.get("APP_ENV")
    active_env = (requested_env or _resolve_environment(doc)).lower()
    env_data = backend.get(active_env, {}) if isinstance(backend.get(active_env), dict) else {}

    merged = _deep_merge(shared, env_data)
    merged.setdefault("app_env", active_env)
    if "ai" in merged:
        merged["ai"] = _resolve_ai_secrets(merged["ai"])
    return merged


_BACKEND_CONFIG = load_backend_config()


def _default_pipeline_home(config_value: Any) -> Path:
    if config_value is None:
        return _REPO_ROOT / ".bio_pipeline"
    candidate = Path(str(config_value)).expanduser()
    if candidate.is_absolute():
        return candidate
    return (_REPO_ROOT / candidate).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            str(_REPO_ROOT / ".env"),
            str(_BACKEND_DIR / ".env"),
        ),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = str(_BACKEND_CONFIG.get("app_name", "Bio Pipeline Manager"))
    app_env: str = str(_BACKEND_CONFIG.get("app_env", "development"))
    log_level: str = str(_BACKEND_CONFIG.get("log_level", "INFO"))
    cors_origins: list[str] = list(
        _BACKEND_CONFIG.get(
            "cors_origins",
            [
                "http://localhost:3005",
                "http://127.0.0.1:3005",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ],
        )
    )
    pipeline_home: Path = _default_pipeline_home(_BACKEND_CONFIG.get("pipeline_home"))
    api_prefix: str = str(_BACKEND_CONFIG.get("api_prefix", "/api/v1"))
    docs_url: str | None = _BACKEND_CONFIG.get("docs_url", "/api/docs")
    redoc_url: str | None = _BACKEND_CONFIG.get("redoc_url", "/api/redoc")

    # Background job worker
    worker_enabled: bool = bool(_BACKEND_CONFIG.get("worker_enabled", True))
    worker_interval: float = float(_BACKEND_CONFIG.get("worker_interval", 2.0))
    worker_parallel: int = int(_BACKEND_CONFIG.get("worker_parallel", 1))
    # Per-task watchdog: kill a task (and its whole process tree) and mark it
    # FAILED if it runs longer than this many seconds, so one wedged task cannot
    # freeze the queue forever. 0 / negative disables the watchdog (unbounded).
    task_timeout_seconds: float = float(_BACKEND_CONFIG.get("task_timeout_seconds", 1800.0))

    # Published-run delivery: output archiving + workspace retention/cleanup.
    reaper_enabled: bool = bool(_BACKEND_CONFIG.get("reaper_enabled", True))
    reaper_interval: float = float(_BACKEND_CONFIG.get("reaper_interval", 5.0))
    artifact_ttl_hours: float = float(_BACKEND_CONFIG.get("artifact_ttl_hours", 24.0))
    # Per-run upload budget (bytes); default 2 GiB.
    upload_max_bytes: int = int(_BACKEND_CONFIG.get("upload_max_bytes", 2 * 1024 * 1024 * 1024))

    auth_session_cookie_name: str = str(_BACKEND_CONFIG.get("auth_session_cookie_name", "bio_pipeline_session"))
    auth_session_ttl_hours: float = float(_BACKEND_CONFIG.get("auth_session_ttl_hours", 24.0))
    auth_secure_cookies: bool = bool(_BACKEND_CONFIG.get("auth_secure_cookies", False))
    ai: dict[str, Any] = Field(default_factory=lambda: dict(_BACKEND_CONFIG.get("ai", {})))

    # Allowlisted shared-storage roots researchers may browse (no FS exposure
    # beyond these). Each entry: {id, label, path}. Empty by default.
    shared_roots: list[dict[str, Any]] = Field(
        default_factory=lambda: list(_BACKEND_CONFIG.get("shared_roots", []))
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
