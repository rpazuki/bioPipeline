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
job: typed_demo
stages:
  - name: run
    pipeline_yaml: demo.yaml
    pipeline: demo
    fanout: {type: none}
    process_arg_mapping:
      step:
        value: original
    output_dir: "/tmp/out"
"""

# A typed field declared inline (no schema_ref) — its key is the schema name "Rule".
RULE_SCHEMA = {
    "name": "Rule",
    "fields": [
        {"name": "value", "type": "integer", "container": "single", "required": True, "options": []},
    ],
}


def _client(tmp_path: Path) -> TestClient:
    app.dependency_overrides.clear()
    get_runtime.cache_clear()
    runtime = create_runtime(tmp_path)
    user = runtime.auth.create_user(username="test-user", password="password123", role=Role.USER)
    app.dependency_overrides[get_runtime] = lambda: runtime
    install_admin_override(app)
    install_user_override(app, user_id=user.id)
    return TestClient(app)


def _typed_job(client: TestClient, *, container: str = "map") -> str:
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    create = client.post(
        "/api/v1/published-jobs/admin",
        json={
            "name": "Typed demo",
            "definition_content": JOB_DEF,
            "status": "published",
            "fields": [
                {
                    "id": "rules",
                    "label": "Replicate rules",
                    "type": "typed",
                    "required": False,
                    "default": {} if container != "list" else [],
                    "help": "Replicate rules",
                    "example": "",
                    "options": [],
                    "container": container,
                    "type_schema": RULE_SCHEMA,
                    "bindings": [
                        {"target": "stage_process_arg", "stage": "run", "process": "step", "parameter": "value"}
                    ],
                }
            ],
        },
    )
    assert create.status_code == 201, create.text
    return create.json()["id"]


def test_explicit_save_lists_updates_and_deletes(tmp_path: Path):
    client = _client(tmp_path)

    saved = client.post(
        "/api/v1/saved-typed-values",
        json={
            "type_key": "Rule",
            "container": "map",
            "type_schema": RULE_SCHEMA,
            "value": {"SLAB": {"value": 3}},
        },
    )
    assert saved.status_code == 201, saved.text
    record = saved.json()
    assert record["label"] == "Rule"  # defaults to the type key
    assert record["value"] == {"SLAB": {"value": 3}}

    # Re-saving the same type + container overwrites in place (stable id, new value).
    again = client.post(
        "/api/v1/saved-typed-values",
        json={"type_key": "Rule", "container": "map", "type_schema": RULE_SCHEMA, "value": {"WELL": {"value": 9}}},
    )
    assert again.json()["id"] == record["id"]
    assert again.json()["value"] == {"WELL": {"value": 9}}

    listed = client.get("/api/v1/saved-typed-values")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = client.patch(f"/api/v1/saved-typed-values/{record['id']}", json={"value": {"WELL": {"value": 1}}})
    assert updated.status_code == 200
    assert updated.json()["value"] == {"WELL": {"value": 1}}

    deleted = client.delete(f"/api/v1/saved-typed-values/{record['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/saved-typed-values").json() == []

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_first_execute_auto_saves_but_later_executes_do_not_overwrite(tmp_path: Path):
    client = _client(tmp_path)
    job_id = _typed_job(client)

    assert client.get("/api/v1/saved-typed-values").json() == []

    # First execute of a not-yet-saved type auto-creates the saved value.
    first = client.post(
        f"/api/v1/published-jobs/catalog/{job_id}/runs",
        json={"values": {"rules": {"SLAB": {"value": 5}}}},
    )
    assert first.status_code == 201, first.text
    saved = client.get("/api/v1/saved-typed-values").json()
    assert len(saved) == 1
    assert saved[0]["type_key"] == "Rule" and saved[0]["container"] == "map"
    assert saved[0]["value"] == {"SLAB": {"value": 5}}

    # A later execute with a different value must NOT overwrite the saved value —
    # only the explicit Save button may update it.
    again = client.post(
        f"/api/v1/published-jobs/catalog/{job_id}/runs",
        json={"values": {"rules": {"WELL": {"value": 9}}}},
    )
    assert again.status_code == 201, again.text
    after = client.get("/api/v1/saved-typed-values").json()
    assert len(after) == 1
    assert after[0]["value"] == {"SLAB": {"value": 5}}  # unchanged by the second run

    # The explicit Save button is still allowed to overwrite it.
    overwrite = client.post(
        "/api/v1/saved-typed-values",
        json={"type_key": "Rule", "container": "map", "type_schema": RULE_SCHEMA, "value": {"WELL": {"value": 9}}},
    )
    assert overwrite.status_code == 201
    assert client.get("/api/v1/saved-typed-values").json()[0]["value"] == {"WELL": {"value": 9}}

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_empty_typed_value_is_not_saved_on_execute(tmp_path: Path):
    client = _client(tmp_path)
    job_id = _typed_job(client)

    run = client.post(f"/api/v1/published-jobs/catalog/{job_id}/runs", json={"values": {"rules": {}}})
    assert run.status_code == 201, run.text
    assert client.get("/api/v1/saved-typed-values").json() == []

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_saved_values_are_scoped_to_the_owner(tmp_path: Path):
    client = _client(tmp_path)
    runtime = app.dependency_overrides[get_runtime]()
    # A saved value belonging to another researcher must be invisible / untouchable.
    other = runtime.typed_values.upsert(
        user_id="someone-else",
        type_key="Rule",
        container="map",
        label="Rule",
        type_schema=RULE_SCHEMA,
        value={"X": {"value": 1}},
    )

    assert client.get("/api/v1/saved-typed-values").json() == []
    assert client.patch(f"/api/v1/saved-typed-values/{other.id}", json={"value": {}}).status_code == 404
    assert client.delete(f"/api/v1/saved-typed-values/{other.id}").status_code == 404

    app.dependency_overrides.clear()
    get_runtime.cache_clear()
