from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient


def _load_app_with_config(config_path: Path, app_env: str, monkeypatch):
    monkeypatch.setenv("APP_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("APP_ENV", app_env)

    import app.core.config as config_module
    import app.main as main_module

    config_module.get_settings.cache_clear()
    config_module = importlib.reload(config_module)
    main_module = importlib.reload(main_module)

    return main_module.app, config_module


def test_config_profiles_control_development_vs_deployed_behavior(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "app_config.yaml"
    config_path.write_text(
        """
defaults:
  environment: development
backend:
  shared:
    app_name: Unified Config App
    worker_enabled: false
    api_prefix: /api/v1
    docs_url: /api/docs
    redoc_url: /api/redoc
  development:
    app_env: development
  production:
    app_env: production
    docs_url: null
    redoc_url: null
""".lstrip(),
        encoding="utf-8",
    )

    dev_app, config_module = _load_app_with_config(config_path, "development", monkeypatch)
    with TestClient(dev_app) as dev_client:
        assert dev_client.get("/health").json()["app"] == "Unified Config App"
        assert dev_client.get("/api/docs").status_code == 200

    config_module.get_settings.cache_clear()

    prod_app, config_module = _load_app_with_config(config_path, "production", monkeypatch)
    with TestClient(prod_app) as prod_client:
        assert prod_client.get("/health").json()["app"] == "Unified Config App"
        assert prod_client.get("/api/docs").status_code == 404

    config_module.get_settings.cache_clear()
