from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_runtime
from app.main import app
from app.services.runtime import create_runtime
from auth_helpers import install_admin_override, install_user_override
from bio_pipeline_manager.auth_models import Role

PIPELINE_YAML = """
pipelines:
  - demo:
      Inputs: []
      Processes:
        - step:
            package: pipeline.helpers.ops
            method: return_value
            parameters:
              value: original
      Outputs:
        - step: result.txt
"""


JOB_DEF = """
job: public_demo
variables:
  tag: [A, B]
defaults:
  root: /tmp/base
stages:
  - name: run
    pipeline_yaml: demo.yaml
    pipeline: demo
    fanout: {type: none}
    process_arg_mapping:
      step:
        value: original
    output_dir: "{root}/{tag}"
"""


def _client(tmp_path: Path) -> TestClient:
    app.dependency_overrides.clear()
    get_runtime.cache_clear()
    runtime = create_runtime(tmp_path)
    user = runtime.auth.create_user(username="test-user", password="password123", role=Role.USER)
    app.dependency_overrides[get_runtime] = lambda: runtime
    install_admin_override(app)
    install_user_override(app, user_id=user.id)
    return TestClient(app)


def _field(field_id: str, label: str, binding: dict, field_type: str = "string", default="x") -> dict:
    return {
        "id": field_id,
        "label": label,
        "type": field_type,
        "required": True,
        "default": default,
        "help": f"Purpose of {label}",
        "example": str(default),
        "options": [],
        "bindings": [binding],
    }


def test_admin_inspects_and_publishes_user_safe_fields(tmp_path: Path):
    client = _client(tmp_path)
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})

    inspect = client.post("/api/v1/published-jobs/admin/inspect", json={"content": JOB_DEF})
    assert inspect.status_code == 200
    candidates = inspect.json()["candidates"]
    candidate_ids = {field["id"] for field in candidates}
    assert "var_tag" in candidate_ids
    assert "stage_run_process_step_value" in candidate_ids
    assert [field["label"] for field in candidates].count("run: step.value") == 1

    create = client.post(
        "/api/v1/published-jobs/admin",
        json={
            "name": "Public demo",
            "description": "User-facing demo",
            "definition_name": "public_demo.yaml",
            "definition_content": JOB_DEF,
            "status": "published",
            "fields": [
                _field(
                    "tag",
                    "Run tag",
                    {"target": "definition_path", "path": ["variables", "tag"]},
                    "enum",
                    "A",
                ),
                _field(
                    "value",
                    "Step value",
                    {"target": "stage_process_arg", "stage": "run", "process": "step", "parameter": "value"},
                    "integer",
                    1,
                ),
            ],
        },
    )
    assert create.status_code == 201
    job_id = create.json()["id"]

    public = client.get(f"/api/v1/published-jobs/catalog/{job_id}")
    assert public.status_code == 200
    assert public.json()["fields"][0]["help"] == "Purpose of Run tag"
    assert "bindings" not in public.json()["fields"][0]

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_user_submits_rewinds_and_sees_own_run(tmp_path: Path):
    client = _client(tmp_path)
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    create = client.post(
        "/api/v1/published-jobs/admin",
        json={
            "name": "Public demo",
            "definition_content": JOB_DEF,
            "status": "published",
            "fields": [
                _field("tag", "Run tag", {"target": "definition_path", "path": ["variables", "tag"]}, "string", "A"),
                _field(
                    "value",
                    "Step value",
                    {"target": "stage_process_arg", "stage": "run", "process": "step", "parameter": "value"},
                    "integer",
                    1,
                ),
            ],
        },
    )
    job_id = create.json()["id"]

    submitted = client.post(f"/api/v1/published-jobs/catalog/{job_id}/runs", json={"values": {"tag": "B", "value": 7}})
    assert submitted.status_code == 201
    run = submitted.json()
    assert run["published_job_name"] == "Public demo"
    assert run["total"] == 1
    Path(run["group"]["tasks"][0]["log_path"]).write_text("published run log\nline two\n", encoding="utf-8")

    runs = client.get("/api/v1/published-jobs/my-runs")
    assert runs.status_code == 200
    assert [item["id"] for item in runs.json()] == [run["id"]]

    detail = client.get(f"/api/v1/published-jobs/my-runs/{run['id']}")
    assert detail.status_code == 200
    task = detail.json()["group"]["tasks"][0]
    assert task["matrix_key"] == {"tag": "B"}
    assert task["process_arg_mapping"] == {"step": {"value": 7}}
    assert detail.json()["logs"][task["id"]] == "published run log\nline two\n"

    rewind = client.post(f"/api/v1/published-jobs/my-runs/{run['id']}/rewind")
    assert rewind.status_code == 201
    assert rewind.json()["values"] == {"tag": "B", "value": 7}

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_admin_lists_usage_validates_and_deletes_drafts(tmp_path: Path):
    client = _client(tmp_path)
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    create = client.post(
        "/api/v1/published-jobs/admin",
        json={
            "name": "Draft demo",
            "definition_content": JOB_DEF,
            "status": "draft",
            "fields": [
                _field("tag", "Run tag", {"target": "definition_path", "path": ["variables", "tag"]}, "string", "A"),
            ],
        },
    )
    assert create.status_code == 201
    draft_id = create.json()["id"]

    validate = client.post(f"/api/v1/published-jobs/admin/{draft_id}/validate")
    assert validate.status_code == 200
    assert validate.json()["field_count"] == 1
    assert validate.json()["run_count"] == 0

    delete = client.delete(f"/api/v1/published-jobs/admin/{draft_id}")
    assert delete.status_code == 204
    assert all(job["id"] != draft_id for job in client.get("/api/v1/published-jobs/admin").json())

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_admin_run_status_and_force_delete_used_job(tmp_path: Path):
    client = _client(tmp_path)
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    create = client.post(
        "/api/v1/published-jobs/admin",
        json={
            "name": "Used demo",
            "definition_content": JOB_DEF,
            "status": "published",
            "fields": [
                _field("tag", "Run tag", {"target": "definition_path", "path": ["variables", "tag"]}, "string", "A"),
            ],
        },
    )
    job_id = create.json()["id"]
    run = client.post(f"/api/v1/published-jobs/catalog/{job_id}/runs", json={"values": {"tag": "A"}})
    assert run.status_code == 201

    all_runs = client.get("/api/v1/published-jobs/admin/runs")
    assert all_runs.status_code == 200
    assert all_runs.json()[0]["published_job_id"] == job_id
    assert all_runs.json()[0]["username"] == "test-user"

    job_runs = client.get(f"/api/v1/published-jobs/admin/{job_id}/runs")
    assert job_runs.status_code == 200
    assert len(job_runs.json()) == 1

    blocked_delete = client.delete(f"/api/v1/published-jobs/admin/{job_id}")
    assert blocked_delete.status_code == 400

    forced_delete = client.delete(f"/api/v1/published-jobs/admin/{job_id}?force=true")
    assert forced_delete.status_code == 204

    app.dependency_overrides.clear()
    get_runtime.cache_clear()
