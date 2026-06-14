from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_runtime
from app.main import app
from app.services.runtime import create_runtime
from auth_helpers import install_admin_override
from bio_pipeline_manager.recurring_job import fire_recurring_job

VALID_YAML = """
pipelines:
  - demo:
      Inputs: []
      Processes: []
      Outputs: []
"""


def _client(tmp_path: Path) -> TestClient:
    app.dependency_overrides.clear()
    get_runtime.cache_clear()
    app.dependency_overrides[get_runtime] = lambda: create_runtime(tmp_path)
    install_admin_override(app)
    client = TestClient(app)
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": VALID_YAML, "overwrite": True})
    return client


def _schedule_payload(tmp_path: Path, **recurrence) -> dict:
    base = {
        "job": {
            "yaml_name": "demo.yaml",
            "pipeline_name": "demo",
            "output_dir": str(tmp_path / "out"),
        },
        "every_n": 1,
        "unit": "days",
        "ends_mode": "never",
    }
    base.update(recurrence)
    return base


def test_create_list_stop_delete_recurring_job(tmp_path: Path):
    client = _client(tmp_path)

    created = client.post("/api/v1/jobs/schedules", json=_schedule_payload(tmp_path))
    assert created.status_code == 201, created.text
    schedule = created.json()
    assert schedule["name"] == "demo"
    assert schedule["active"] is True and schedule["runs_done"] == 0

    listed = client.get("/api/v1/jobs/schedules")
    assert listed.status_code == 200
    assert [s["id"] for s in listed.json()] == [schedule["id"]]

    stopped = client.post(f"/api/v1/jobs/schedules/{schedule['id']}/stop")
    assert stopped.status_code == 200 and stopped.json()["active"] is False

    assert client.delete(f"/api/v1/jobs/schedules/{schedule['id']}").status_code == 204
    assert client.get("/api/v1/jobs/schedules").json() == []

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_create_recurring_job_rejects_unknown_yaml(tmp_path: Path):
    client = _client(tmp_path)
    payload = _schedule_payload(tmp_path)
    payload["job"]["yaml_name"] = "missing.yaml"
    assert client.post("/api/v1/jobs/schedules", json=payload).status_code == 400
    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_firing_submits_jobs_and_respects_end_rule(tmp_path: Path):
    client = _client(tmp_path)
    runtime = app.dependency_overrides[get_runtime]()

    schedule_id = client.post(
        "/api/v1/jobs/schedules",
        json=_schedule_payload(tmp_path, every_n=1, unit="minutes", ends_mode="count", ends_count=2),
    ).json()["id"]

    assert client.get("/api/v1/jobs").json() == []

    def fire_once():
        fire_recurring_job(
            queue=runtime.queue,
            yaml_resolver=runtime.yaml_store.resolve_name,
            jobs=runtime.recurring_jobs,
            record=runtime.recurring_jobs.get(schedule_id),
        )

    fire_once()
    jobs = client.get("/api/v1/jobs").json()
    assert len(jobs) == 1 and jobs[0]["pipeline_name"] == "demo"
    assert runtime.recurring_jobs.get(schedule_id).runs_done == 1
    assert runtime.recurring_jobs.get(schedule_id).active is True

    fire_once()
    assert len(client.get("/api/v1/jobs").json()) == 2
    ended = runtime.recurring_jobs.get(schedule_id)
    assert ended.runs_done == 2 and ended.active is False

    app.dependency_overrides.clear()
    get_runtime.cache_clear()
