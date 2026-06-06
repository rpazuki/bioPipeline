from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_runtime
from app.main import app
from app.services.runtime import create_runtime


VALID_YAML = """
pipelines:
  - demo:
      Inputs: []
      Processes: []
      Outputs: []
"""


def _definition() -> str:
    return """
job: api_demo
variables: {tag: [T1, T2]}
stages:
  - name: first
    pipeline_yaml: demo.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out/{tag}/a
  - name: second
    needs: [first]
    pipeline_yaml: demo.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out/{tag}/b
"""


def _client(tmp_path: Path) -> TestClient:
    app.dependency_overrides.clear()
    get_runtime.cache_clear()
    app.dependency_overrides[get_runtime] = lambda: create_runtime(tmp_path)
    return TestClient(app)


def test_preview_expands_without_queueing(tmp_path: Path):
    client = _client(tmp_path)
    response = client.post("/api/v1/job-definitions/preview", json={"content": _definition()})

    assert response.status_code == 200
    body = response.json()
    assert body["job_name"] == "api_demo"
    assert body["task_count"] == 4  # 2 tags x 2 stages
    assert {t["stage"] for t in body["tasks"]} == {"first", "second"}

    # Preview must not create any jobs.
    assert client.get("/api/v1/jobs").json() == []

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_preview_invalid_definition_returns_400(tmp_path: Path):
    client = _client(tmp_path)
    response = client.post("/api/v1/job-definitions/preview", json={"content": "job: bad\n"})
    assert response.status_code == 400

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_preview_missing_mapping_file_returns_400_not_500(tmp_path: Path):
    """A fan-out source that cannot be read is a client error, not a server crash."""
    client = _client(tmp_path)
    content = (
        "job: m\n"
        "stages:\n"
        "  - name: prep\n"
        "    pipeline_yaml: demo.yaml\n"
        "    pipeline: demo\n"
        "    fanout: {type: mapping_file, mapping: definitely_missing.yaml}\n"
        "    output_dir: /out\n"
    )
    response = client.post("/api/v1/job-definitions/preview", json={"content": content})
    assert response.status_code == 400
    assert "mapping" in response.json()["detail"].lower()

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_submit_lists_and_fetches_group(tmp_path: Path):
    client = _client(tmp_path)
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": VALID_YAML, "overwrite": True})

    submit = client.post("/api/v1/job-definitions", json={"content": _definition()})
    assert submit.status_code == 201
    group = submit.json()
    parent_id = group["parent_job_id"]
    assert group["job_name"] == "api_demo"
    assert group["total"] == 4
    assert group["status"] in {"queued", "running"}
    assert len(group["tasks"]) == 4
    # Tasks expose their stage + matrix cell so the UI can group them hierarchically.
    assert {t["stage"] for t in group["tasks"]} == {"first", "second"}
    assert all("tag" in t["matrix_key"] for t in group["tasks"])

    listing = client.get("/api/v1/job-definitions")
    assert listing.status_code == 200
    assert any(g["parent_job_id"] == parent_id for g in listing.json())

    detail = client.get(f"/api/v1/job-definitions/{parent_id}")
    assert detail.status_code == 200
    assert detail.json()["total"] == 4

    missing = client.get("/api/v1/job-definitions/does-not-exist")
    assert missing.status_code == 404

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_submit_invalid_yaml_reference_returns_400(tmp_path: Path):
    client = _client(tmp_path)
    # pipeline_yaml escapes the YAML store -> resolve_name raises ValueError -> 400.
    bad = _definition().replace("demo.yaml", "../escape.yaml")
    response = client.post("/api/v1/job-definitions", json={"content": bad})
    assert response.status_code == 400

    app.dependency_overrides.clear()
    get_runtime.cache_clear()
