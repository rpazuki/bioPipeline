from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_runtime
from app.main import app
from app.services.runtime import create_runtime
from auth_helpers import install_admin_override, install_user_override
from bio_pipeline_manager.auth_models import Role
from bio_pipeline_manager.published_runs import fire_recurring_schedule

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

JOB_DEF_UPLOAD = """
job: upload_demo
stages:
  - name: run
    pipeline_yaml: demo.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: "/server/out"
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


def _upload_job(client: TestClient) -> tuple[str, str]:
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    field = {
        "id": "raw_data",
        "label": "Raw",
        "type": "file",
        "required": True,
        "default": "",
        "help": "Raw",
        "example": "",
        "options": [],
        "io_role": "input",
        "sources": ["upload"],
        "bindings": [{"target": "stage_input_source", "stage": "run", "input": "raw_data"}],
    }
    job_id = client.post(
        "/api/v1/published-jobs/admin",
        json={"name": "Recurring demo", "definition_content": JOB_DEF_UPLOAD, "status": "published", "fields": [field]},
    ).json()["id"]
    workspace_id = client.post(f"/api/v1/published-jobs/catalog/{job_id}/runs/draft").json()["workspace_id"]
    client.post(
        f"/api/v1/published-jobs/catalog/{job_id}/runs/{workspace_id}/uploads/raw_data?filename=in.csv",
        content=b"hello",
    )
    return job_id, workspace_id


def test_create_list_stop_and_delete_schedule(tmp_path: Path):
    client = _client(tmp_path)
    job_id, workspace_id = _upload_job(client)

    created = client.post(
        f"/api/v1/published-jobs/catalog/{job_id}/schedules",
        json={
            "values": {"raw_data": ""},
            "workspace_id": workspace_id,
            "file_bindings": {"raw_data": {"kind": "upload", "path": "inputs/raw_data/in.csv"}},
            "every_n": 1,
            "unit": "days",
            "ends_mode": "count",
            "ends_count": 3,
        },
    )
    assert created.status_code == 201, created.text
    schedule = created.json()
    assert schedule["active"] is True
    assert schedule["every_n"] == 1 and schedule["unit"] == "days"
    assert schedule["runs_done"] == 0

    listed = client.get("/api/v1/published-jobs/my-schedules")
    assert listed.status_code == 200
    assert [s["id"] for s in listed.json()] == [schedule["id"]]

    stopped = client.post(f"/api/v1/published-jobs/my-schedules/{schedule['id']}/stop")
    assert stopped.status_code == 200 and stopped.json()["active"] is False

    deleted = client.delete(f"/api/v1/published-jobs/my-schedules/{schedule['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/published-jobs/my-schedules").json() == []

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_firing_clones_inputs_creates_runs_and_respects_end_rule(tmp_path: Path):
    client = _client(tmp_path)
    runtime = app.dependency_overrides[get_runtime]()
    job_id, workspace_id = _upload_job(client)

    schedule_id = client.post(
        f"/api/v1/published-jobs/catalog/{job_id}/schedules",
        json={
            "values": {"raw_data": ""},
            "workspace_id": workspace_id,
            "file_bindings": {"raw_data": {"kind": "upload", "path": "inputs/raw_data/in.csv"}},
            "every_n": 1,
            "unit": "minutes",
            "ends_mode": "count",
            "ends_count": 2,
        },
    ).json()["id"]

    def fire_once():
        fire_recurring_schedule(
            published_jobs=runtime.published_jobs,
            queue=runtime.queue,
            run_workspaces=runtime.run_workspaces,
            shared=runtime.shared_storage,
            yaml_resolver=runtime.yaml_store.resolve_name,
            schedules=runtime.recurring_schedules,
            schedule=runtime.recurring_schedules.get(schedule_id),
        )

    assert client.get("/api/v1/published-jobs/my-runs").json() == []

    fire_once()
    runs = client.get("/api/v1/published-jobs/my-runs").json()
    assert len(runs) == 1
    # The occurrence cloned the template inputs into its own workspace.
    new_ws = runs[0]["workspace_id"]
    assert new_ws and new_ws != workspace_id
    assert runtime.run_workspaces.input_abspath(new_ws, "inputs/raw_data/in.csv").read_bytes() == b"hello"
    sched = runtime.recurring_schedules.get(schedule_id)
    assert sched.runs_done == 1 and sched.active is True

    fire_once()
    assert len(client.get("/api/v1/published-jobs/my-runs").json()) == 2
    sched = runtime.recurring_schedules.get(schedule_id)
    assert sched.runs_done == 2 and sched.active is False  # end-after-2-runs reached

    app.dependency_overrides.clear()
    get_runtime.cache_clear()
