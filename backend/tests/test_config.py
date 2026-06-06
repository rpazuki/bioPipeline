from __future__ import annotations

from pathlib import Path

from app.core import config as config_module


def test_load_backend_config_merges_shared_and_profile(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "app_config.yaml"
    config_path.write_text(
        """
defaults:
  environment: development
backend:
  shared:
    app_name: Shared Name
    api_prefix: /api/v1
    worker_enabled: true
    docs_url: /api/docs
    pipeline_home: .bio_pipeline
  production:
    app_env: production
    worker_enabled: false
    docs_url: null
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("APP_ENV", "production")

    merged = config_module.load_backend_config()

    assert merged["app_name"] == "Shared Name"
    assert merged["app_env"] == "production"
    assert merged["worker_enabled"] is False
    assert merged["docs_url"] is None


def test_settings_allow_environment_override(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "app_config.yaml"
    config_path.write_text(
        """
defaults:
  environment: development
backend:
  shared:
    worker_parallel: 1
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("WORKER_PARALLEL", "4")

    config_module.get_settings.cache_clear()
    settings = config_module.get_settings()

    assert settings.worker_parallel == 4

    config_module.get_settings.cache_clear()
