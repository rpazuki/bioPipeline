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


def test_split_routes_storage_validation_templates_and_jobs(tmp_path: Path):
    app.dependency_overrides.clear()
    get_runtime.cache_clear()
    app.dependency_overrides[get_runtime] = lambda: create_runtime(tmp_path)
    client = TestClient(app)

    assert client.get("/health").json()["status"] == "ok"

    template_response = client.get("/api/v1/templates/empty")
    assert template_response.status_code == 200
    assert "new_pipeline" in template_response.json()["content"]

    validation_response = client.post("/api/v1/validation/yaml", json={"content": VALID_YAML})
    assert validation_response.status_code == 200
    assert validation_response.json()["is_valid"] is True

    save_response = client.post(
        "/api/v1/pipeline-yamls",
        json={"name": "demo.yaml", "content": VALID_YAML, "overwrite": True},
    )
    assert save_response.status_code == 201
    assert save_response.json()["pipelines"] == ["demo"]

    job_response = client.post(
        "/api/v1/jobs",
        json={"yaml_name": "demo.yaml", "pipeline_name": "demo", "output_dir": str(tmp_path / "out")},
    )
    assert job_response.status_code == 201
    assert job_response.json()["status"] == "queued"

    app.dependency_overrides.clear()
    get_runtime.cache_clear()

