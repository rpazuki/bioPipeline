from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_runtime
from app.main import app
from app.services.runtime import create_runtime


def _client(tmp_path: Path) -> TestClient:
    app.dependency_overrides.clear()
    get_runtime.cache_clear()
    app.dependency_overrides[get_runtime] = lambda: create_runtime(tmp_path)
    return TestClient(app)


def test_list_job_definition_templates(tmp_path: Path):
    client = _client(tmp_path)

    response = client.get("/api/v1/job-definition-templates")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()}
    assert {"empty", "matrix_sweep", "preprocess_collate"} <= names


def test_get_job_definition_template(tmp_path: Path):
    client = _client(tmp_path)

    response = client.get("/api/v1/job-definition-templates/empty")
    assert response.status_code == 200
    assert "new_job" in response.json()["content"]


def test_get_unknown_job_definition_template(tmp_path: Path):
    client = _client(tmp_path)

    response = client.get("/api/v1/job-definition-templates/nope")
    assert response.status_code == 404
