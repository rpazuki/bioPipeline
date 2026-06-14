from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_runtime
from app.main import app
from app.services.runtime import create_runtime
from auth_helpers import install_admin_override


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
    install_admin_override(app)
    client = TestClient(app)

    assert client.get("/health").json()["status"] == "ok"

    runtime_response = client.get("/api/v1/runtime")
    assert runtime_response.status_code == 200
    assert runtime_response.json()["yaml_root"] == str(tmp_path / "yamls")
    assert runtime_response.json()["yaml_files"] == []

    folder_response = client.post("/api/v1/pipeline-yamls/folders", json={"path": "designs/alpha"})
    assert folder_response.status_code == 201
    assert folder_response.json()["path"] == "designs/alpha"

    template_response = client.get("/api/v1/templates/empty")
    assert template_response.status_code == 200
    assert "new_pipeline" in template_response.json()["content"]

    validation_response = client.post("/api/v1/validation/yaml", json={"content": VALID_YAML})
    assert validation_response.status_code == 200
    assert validation_response.json()["is_valid"] is True

    save_response = client.post(
        "/api/v1/pipeline-yamls",
        json={"name": "designs/alpha/demo.yaml", "content": VALID_YAML, "overwrite": True},
    )
    assert save_response.status_code == 201
    assert save_response.json()["name"] == "designs/alpha/demo.yaml"
    assert save_response.json()["pipelines"] == ["demo"]

    tree_response = client.get("/api/v1/pipeline-yamls/tree")
    assert tree_response.status_code == 200
    assert tree_response.json()[0]["path"] == "designs"
    assert tree_response.json()[0]["children"][0]["path"] == "designs/alpha"
    assert tree_response.json()[0]["children"][0]["children"][0]["path"] == "designs/alpha/demo.yaml"

    move_response = client.post(
        "/api/v1/pipeline-yamls/move",
        json={"source_path": "designs/alpha/demo.yaml", "destination_path": "designs/beta/demo.yaml"},
    )
    assert move_response.status_code == 200
    assert move_response.json()["name"] == "designs/beta/demo.yaml"

    moved_tree_response = client.get("/api/v1/pipeline-yamls/tree")
    assert moved_tree_response.status_code == 200
    assert moved_tree_response.json()[0]["children"][0]["path"] == "designs/beta"
    assert moved_tree_response.json()[0]["children"][0]["children"][0]["path"] == "designs/beta/demo.yaml"

    job_response = client.post(
        "/api/v1/jobs",
        json={"yaml_name": "designs/beta/demo.yaml", "pipeline_name": "demo", "output_dir": str(tmp_path / "out")},
    )
    assert job_response.status_code == 201
    assert job_response.json()["status"] == "queued"

    rewind_response = client.post(f"/api/v1/jobs/{job_response.json()['id']}/rewind")
    assert rewind_response.status_code == 201
    assert rewind_response.json()["pipeline_name"] == "demo"
    assert rewind_response.json()["created_at"] >= job_response.json()["created_at"]

    # Schedule again: rewinding with scheduled_at defers the new job to that time.
    scheduled = client.post(
        f"/api/v1/jobs/{job_response.json()['id']}/rewind",
        json={"scheduled_at": "2099-01-01T00:00:00+00:00"},
    )
    assert scheduled.status_code == 201
    assert scheduled.json()["scheduled_at"].startswith("2099-01-01")

    delete_job_response = client.delete(f"/api/v1/jobs/{job_response.json()['id']}")
    assert delete_job_response.status_code == 204

    missing_job_response = client.get(f"/api/v1/jobs/{job_response.json()['id']}")
    assert missing_job_response.status_code == 404

    delete_response = client.delete("/api/v1/pipeline-yamls/designs/beta/demo.yaml")
    assert delete_response.status_code == 204

    deleted_tree_response = client.get("/api/v1/pipeline-yamls/tree")
    assert deleted_tree_response.status_code == 200
    assert deleted_tree_response.json()[0]["children"][0]["path"] == "designs/beta"
    assert deleted_tree_response.json()[0]["children"][0]["children"] == []

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_job_submit_round_trips_process_arg_mapping(tmp_path: Path):
    app.dependency_overrides.clear()
    get_runtime.cache_clear()
    app.dependency_overrides[get_runtime] = lambda: create_runtime(tmp_path)
    install_admin_override(app)
    client = TestClient(app)

    client.post(
        "/api/v1/pipeline-yamls",
        json={"name": "demo.yaml", "content": VALID_YAML, "overwrite": True},
    )

    create = client.post(
        "/api/v1/jobs",
        json={
            "yaml_name": "demo.yaml",
            "pipeline_name": "demo",
            "output_dir": str(tmp_path / "out"),
            "process_arg_mapping": {"step": {"threshold": "0.5"}},
        },
    )
    assert create.status_code == 201
    assert create.json()["process_arg_mapping"] == {"step": {"threshold": "0.5"}}

    fetched = client.get(f"/api/v1/jobs/{create.json()['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["process_arg_mapping"] == {"step": {"threshold": "0.5"}}

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_yaml_list_includes_invalid_yaml_files(tmp_path: Path):
    app.dependency_overrides.clear()
    get_runtime.cache_clear()
    runtime = create_runtime(tmp_path)
    app.dependency_overrides[get_runtime] = lambda: runtime
    install_admin_override(app)
    client = TestClient(app)

    nested = tmp_path / "yamls" / "drafts"
    nested.mkdir(parents=True)
    (nested / "not_pipeline.yaml").write_text("custom_mapping: {}\n", encoding="utf-8")

    response = client.get("/api/v1/pipeline-yamls")

    assert response.status_code == 200
    assert response.json() == [
        {
            "name": "drafts/not_pipeline.yaml",
            "pipelines": [],
            "is_valid": False,
            "error": "YAML must contain a non-empty 'pipelines' list",
        }
    ]

    detail_response = client.get("/api/v1/pipeline-yamls/drafts/not_pipeline.yaml")
    assert detail_response.status_code == 200
    assert detail_response.json()["content"] == "custom_mapping: {}\n"
    assert detail_response.json()["is_valid"] is False

    tree_response = client.get("/api/v1/pipeline-yamls/tree")
    assert tree_response.status_code == 200
    assert tree_response.json()[0]["path"] == "drafts"
    assert tree_response.json()[0]["children"][0]["is_valid"] is False

    runtime_response = client.get("/api/v1/runtime")
    assert runtime_response.status_code == 200
    assert runtime_response.json()["yaml_root"] == str(tmp_path / "yamls")
    assert runtime_response.json()["yaml_files"] == ["drafts/not_pipeline.yaml"]

    delete_folder = client.delete("/api/v1/pipeline-yamls/folders/drafts")
    assert delete_folder.status_code == 400

    app.dependency_overrides.clear()
    get_runtime.cache_clear()
