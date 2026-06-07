from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


_THIS_FILE = Path(__file__).resolve()
_BACKEND_DIR = _THIS_FILE.parents[2]
_REPO_ROOT = _THIS_FILE.parents[3]
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "configs" / "app_config.yaml"


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

    auth_session_cookie_name: str = str(_BACKEND_CONFIG.get("auth_session_cookie_name", "bio_pipeline_session"))
    auth_session_ttl_hours: float = float(_BACKEND_CONFIG.get("auth_session_ttl_hours", 24.0))
    auth_secure_cookies: bool = bool(_BACKEND_CONFIG.get("auth_secure_cookies", False))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
