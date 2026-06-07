from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_runtime
from app.core.config import settings
from app.main import app
from app.services.runtime import create_runtime
from auth_helpers import install_admin_override


PIPELINE_YAML = """
pipelines:
  - demo:
      Inputs: []
      Processes: []
      Outputs: []
"""

JOB_DEF = """
job: ai_demo
variables:
  tag: [A]
stages:
  - name: run
    pipeline_yaml: demo.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /tmp/ai-demo/{tag}
"""


def _client(tmp_path: Path) -> TestClient:
    app.dependency_overrides.clear()
    get_runtime.cache_clear()
    app.dependency_overrides[get_runtime] = lambda: create_runtime(tmp_path)
    install_admin_override(app)
    return TestClient(app)


def _reset() -> None:
    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def _set_fake_ai_config(monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "ai",
        {
            "default_provider": "fake",
            "max_tool_iterations": 4,
            "providers": {
                "fake": {
                    "enabled": True,
                    "api_key": "secret-test-key",
                    "model": "fake-model",
                    "base_url": "http://fake.local",
                }
            },
        },
    )


def test_ai_routes_require_admin(tmp_path: Path):
    app.dependency_overrides.clear()
    get_runtime.cache_clear()
    app.dependency_overrides[get_runtime] = lambda: create_runtime(tmp_path)
    client = TestClient(app)

    assert client.get("/api/v1/ai-chat/context").status_code == 401

    _reset()


def test_context_and_schema_hide_provider_keys(tmp_path: Path, monkeypatch):
    _set_fake_ai_config(monkeypatch)
    client = _client(tmp_path)

    context = client.get("/api/v1/ai-chat/context")
    assert context.status_code == 200
    body = context.json()
    assert body["default_provider"] == "fake"
    assert body["providers"] == [
        {
            "provider": "fake",
            "enabled": True,
            "configured": True,
            "model": "fake-model",
            "base_url": "http://fake.local",
            "is_default": True,
        }
    ]
    assert "secret-test-key" not in str(body)
    assert body["schema_digest"]
    assert any(tool["name"] == "validate_pipeline_yaml" for tool in body["tools"])

    schema = client.get("/api/v1/ai-chat/schema")
    assert schema.status_code == 200
    schema_body = schema.json()
    assert schema_body["digest"] == body["schema_digest"]
    assert "PublishedField" in schema_body["published_job"]["pydantic"]
    assert "secret-test-key" not in str(schema_body)

    _reset()


def test_provider_test_uses_backend_config(tmp_path: Path, monkeypatch):
    _set_fake_ai_config(monkeypatch)
    client = _client(tmp_path)

    response = client.post("/api/v1/ai-chat/test-provider", json={"provider": "fake"})
    assert response.status_code == 200
    assert response.json()["provider"] == "fake"
    assert response.json()["model"] == "fake-model"

    _reset()


def test_ai_tools_validate_save_preview_and_confirmation(tmp_path: Path, monkeypatch):
    _set_fake_ai_config(monkeypatch)
    client = _client(tmp_path)

    validate = client.post(
        "/api/v1/ai-chat/tools/execute",
        json={"name": "validate_pipeline_yaml", "arguments": {"content": PIPELINE_YAML}},
    )
    assert validate.status_code == 200
    assert validate.json()["status"] == "succeeded"
    assert validate.json()["result"]["is_valid"] is True

    save_yaml = client.post(
        "/api/v1/ai-chat/tools/execute",
        json={
            "name": "save_pipeline_yaml",
            "arguments": {"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True},
        },
    )
    assert save_yaml.status_code == 200
    assert save_yaml.json()["status"] == "succeeded"
    assert save_yaml.json()["result"]["pipelines"] == ["demo"]

    save_def = client.post(
        "/api/v1/ai-chat/tools/execute",
        json={
            "name": "save_job_definition",
            "arguments": {"name": "ai_demo.yaml", "content": JOB_DEF, "overwrite": True},
        },
    )
    assert save_def.status_code == 200
    assert save_def.json()["result"]["job"] == "ai_demo"

    preview = client.post(
        "/api/v1/ai-chat/tools/execute",
        json={"name": "preview_job_definition", "arguments": {"content": JOB_DEF}},
    )
    assert preview.status_code == 200
    assert preview.json()["result"]["task_count"] == 1

    blocked_submit = client.post(
        "/api/v1/ai-chat/tools/execute",
        json={"name": "submit_job_definition", "arguments": {"content": JOB_DEF}},
    )
    assert blocked_submit.status_code == 200
    assert blocked_submit.json()["status"] == "pending_confirmation"

    confirmed_submit = client.post(
        "/api/v1/ai-chat/tools/execute",
        json={
            "name": "submit_job_definition",
            "arguments": {"content": JOB_DEF},
            "confirmed": True,
        },
    )
    assert confirmed_submit.status_code == 200
    assert confirmed_submit.json()["status"] == "succeeded"
    assert confirmed_submit.json()["result"]["parent_job_id"]

    _reset()


def test_ai_tools_create_draft_and_publish_requires_confirmation(tmp_path: Path, monkeypatch):
    _set_fake_ai_config(monkeypatch)
    client = _client(tmp_path)
    field = {
        "id": "tag",
        "label": "Run tag",
        "type": "string",
        "required": True,
        "default": "A",
        "help": "Selects the run tag.",
        "example": "A",
        "options": [],
        "bindings": [{"target": "definition_path", "path": ["variables", "tag"]}],
    }

    create = client.post(
        "/api/v1/ai-chat/tools/execute",
        json={
            "name": "create_published_job_draft",
            "arguments": {
                "name": "AI demo",
                "description": "Draft from AI",
                "definition_name": "ai_demo.yaml",
                "definition_content": JOB_DEF,
                "fields": [field],
            },
        },
    )
    assert create.status_code == 200
    assert create.json()["status"] == "succeeded"
    draft = create.json()["result"]
    assert draft["status"] == "draft"

    blocked_publish = client.post(
        "/api/v1/ai-chat/tools/execute",
        json={"name": "publish_published_job", "arguments": {"published_job_id": draft["id"]}},
    )
    assert blocked_publish.status_code == 200
    assert blocked_publish.json()["status"] == "pending_confirmation"

    published = client.post(
        "/api/v1/ai-chat/tools/execute",
        json={
            "name": "publish_published_job",
            "arguments": {"published_job_id": draft["id"]},
            "confirmed": True,
        },
    )
    assert published.status_code == 200
    assert published.json()["result"]["status"] == "published"

    _reset()
