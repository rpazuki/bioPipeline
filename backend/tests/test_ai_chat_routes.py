from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

import app.api.routes.ai_chat as ai_chat_routes
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

    inspect = client.post(
        "/api/v1/ai-chat/tools/execute",
        json={"name": "inspect_published_job_fields", "arguments": {"content": JOB_DEF}},
    )
    assert inspect.status_code == 200
    assert inspect.json()["status"] == "succeeded"
    assert inspect.json()["result"]["job_name"] == "ai_demo"
    assert isinstance(inspect.json()["result"]["candidates"], list)

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


def test_ai_save_tools_hidden_from_model_but_executable(tmp_path: Path, monkeypatch):
    _set_fake_ai_config(monkeypatch)
    client = _client(tmp_path)

    context = client.get("/api/v1/ai-chat/context")
    tool_names = {tool["name"] for tool in context.json()["tools"]}

    # The AI can design a Published Job by inspecting its fields ...
    assert "inspect_published_job_fields" in tool_names
    # ... but it never saves or publishes: the save tools and any
    # create/publish tools are not advertised to the model.
    for hidden in (
        "save_pipeline_yaml",
        "save_job_definition",
        "create_published_job_draft",
        "publish_published_job",
        "list_published_jobs_admin",
    ):
        assert hidden not in tool_names

    # Save tools remain reachable through the explicit admin execute path (the UI
    # Save button), so admins can still persist a reviewed draft.
    saved = client.post(
        "/api/v1/ai-chat/tools/execute",
        json={
            "name": "save_pipeline_yaml",
            "arguments": {"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True},
        },
    )
    assert saved.status_code == 200
    assert saved.json()["status"] == "succeeded"

    # A genuinely unknown tool still fails.
    blocked = client.post(
        "/api/v1/ai-chat/tools/execute",
        json={"name": "create_published_job_draft", "arguments": {}},
    )
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "failed"
    assert "Unknown AI tool" in blocked.json()["error"]

    _reset()


def test_ai_messages_text_only(tmp_path: Path, monkeypatch):
    _set_fake_ai_config(monkeypatch)
    client = _client(tmp_path)

    response = client.post(
        "/api/v1/ai-chat/messages",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert "Fake provider received: hello" in body["message"]["content"]
    assert body["tool_calls"] == []
    assert body["needs_confirmation"] is None

    _reset()


def test_ai_messages_runs_read_only_tool(tmp_path: Path, monkeypatch):
    _set_fake_ai_config(monkeypatch)
    client = _client(tmp_path)

    response = client.post(
        "/api/v1/ai-chat/messages",
        json={"messages": [{"role": "user", "content": "@tool list_pipeline_yamls {}"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["tool_calls"]) == 1
    call = body["tool_calls"][0]
    assert call["name"] == "list_pipeline_yamls"
    assert call["status"] == "succeeded"
    assert "list_pipeline_yamls" in body["message"]["content"]
    assert body["needs_confirmation"] is None

    _reset()


def test_ai_messages_streams_heartbeats_before_result(tmp_path: Path, monkeypatch):
    _set_fake_ai_config(monkeypatch)
    client = _client(tmp_path)

    # Force a turn that outlasts several heartbeat intervals so the keepalive
    # path (not just the instant final line) is exercised.
    monkeypatch.setattr(ai_chat_routes, "_HEARTBEAT_SECONDS", 0.05)

    def _slow_turn(body, runtime, admin):  # noqa: ANN001 - test stub
        time.sleep(0.25)
        return {
            "message": {"role": "assistant", "content": "slow done"},
            "tool_calls": [],
            "drafts": [],
            "needs_confirmation": None,
        }

    monkeypatch.setattr(ai_chat_routes, "_run_chat_turn", _slow_turn)

    response = client.post(
        "/api/v1/ai-chat/messages",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 200
    # Heartbeats are blank lines emitted before the single JSON result line.
    assert response.text.startswith("\n")
    lines = [line for line in response.text.split("\n") if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[-1])["message"]["content"] == "slow done"

    _reset()


def test_ai_messages_error_is_carried_in_stream_body(tmp_path: Path, monkeypatch):
    _set_fake_ai_config(monkeypatch)
    client = _client(tmp_path)

    def _boom(body, runtime, admin):  # noqa: ANN001 - test stub
        return ai_chat_routes._error_payload(502, "AI chat failed: boom")

    monkeypatch.setattr(ai_chat_routes, "_run_chat_turn", _boom)

    response = client.post(
        "/api/v1/ai-chat/messages",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    # The HTTP status stays 200 once streaming starts; the error rides in the body.
    assert response.status_code == 200
    payload = json.loads(response.text.strip().splitlines()[-1])
    assert payload["error"]["status"] == 502
    assert "boom" in payload["error"]["detail"]

    _reset()


def test_ai_messages_high_impact_tool_needs_confirmation(tmp_path: Path, monkeypatch):
    _set_fake_ai_config(monkeypatch)
    client = _client(tmp_path)

    directive = "@tool submit_job_definition " + json.dumps({"content": JOB_DEF})
    response = client.post(
        "/api/v1/ai-chat/messages",
        json={"messages": [{"role": "user", "content": directive}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["needs_confirmation"] is not None
    assert body["needs_confirmation"]["name"] == "submit_job_definition"
    assert body["needs_confirmation"]["status"] == "pending_confirmation"

    _reset()
