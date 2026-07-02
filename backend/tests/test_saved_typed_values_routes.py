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


def _plain_saveable_job(client: TestClient, *, io_role: str = "none"):
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    return client.post(
        "/api/v1/published-jobs/admin",
        json={
            "name": "Plain demo",
            "definition_content": JOB_DEF,
            "status": "published",
            "fields": [
                {
                    "id": "step_value",
                    "label": "Step value",
                    "type": "string",
                    "required": True,
                    "default": "original",
                    "saveable": True,
                    "io_role": io_role,
                    "options": [],
                    "bindings": [
                        {"target": "stage_process_arg", "stage": "run", "process": "step", "parameter": "value"}
                    ],
                }
            ],
        },
    )


def test_saveable_plain_field_auto_saves_and_reuses_metadata(tmp_path: Path):
    client = _client(tmp_path)
    create = _plain_saveable_job(client)
    assert create.status_code == 201, create.text

    run = client.post(
        f"/api/v1/published-jobs/catalog/{create.json()['id']}/runs",
        json={"values": {"step_value": "remember me"}},
    )
    assert run.status_code == 201, run.text

    [saved] = client.get("/api/v1/saved-typed-values").json()
    assert saved["type_key"] == f"job:{create.json()['id']}:field:step_value:string"
    assert saved["value_kind"] == "plain"
    assert saved["label"] == "Step value"
    assert saved["field_schema"]["type"] == "string"
    assert saved["value"] == "remember me"

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_saveable_is_rejected_for_file_managed_fields(tmp_path: Path):
    client = _client(tmp_path)
    create = _plain_saveable_job(client, io_role="input")
    assert create.status_code == 400
    assert "only be saveable when it is server-managed" in create.json()["detail"]

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


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


# --- Multi-instance saved cases ---------------------------------------------- #
# A type is multi-instance when its resolved schema carries `multiple` (inline) or its
# library entry sets it. These use an inline `multiple` schema keyed by a name not in
# the library, exercising the schema fallback in the route's `_resolve_multiple`.
MULTI_SCHEMA = {**RULE_SCHEMA, "multiple": True}


def _save_case(client: TestClient, name: str, value: dict, **extra):
    body = {"type_key": "RuleMulti", "container": "single", "name": name, "type_schema": MULTI_SCHEMA, "value": value}
    body.update(extra)
    return client.post("/api/v1/saved-typed-values", json=body)


def test_multiple_type_keeps_named_cases(tmp_path: Path):
    client = _client(tmp_path)

    slab = _save_case(client, "SLAB", {"value": 3})
    assert slab.status_code == 201, slab.text
    assert slab.json()["name"] == "SLAB"
    assert slab.json()["is_default"] is True  # the first case becomes the default
    assert slab.json()["multiple"] is True

    wt = _save_case(client, "WT", {"value": 2})
    assert wt.json()["name"] == "WT"
    assert wt.json()["is_default"] is False

    listed = client.get("/api/v1/saved-typed-values").json()
    assert len(listed) == 2
    assert {record["name"] for record in listed} == {"SLAB", "WT"}

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_multiple_type_requires_a_case_name(tmp_path: Path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/v1/saved-typed-values",
        json={"type_key": "RuleMulti", "container": "single", "type_schema": MULTI_SCHEMA, "value": {"value": 1}},
    )
    assert resp.status_code == 400
    assert "case name" in resp.json()["detail"].lower()

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_single_instance_ignores_name_and_overwrites(tmp_path: Path):
    client = _client(tmp_path)
    # RULE_SCHEMA has no `multiple`, so a sent name is forced empty and re-saving replaces.
    first = client.post(
        "/api/v1/saved-typed-values",
        json={"type_key": "Rule", "container": "single", "name": "ignored", "type_schema": RULE_SCHEMA, "value": {"value": 1}},
    )
    assert first.status_code == 201
    assert first.json()["name"] == ""
    assert first.json()["multiple"] is False

    again = client.post(
        "/api/v1/saved-typed-values",
        json={"type_key": "Rule", "container": "single", "name": "also-ignored", "type_schema": RULE_SCHEMA, "value": {"value": 2}},
    )
    assert again.json()["id"] == first.json()["id"]
    assert len(client.get("/api/v1/saved-typed-values").json()) == 1

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_make_default_moves_flag_via_patch(tmp_path: Path):
    client = _client(tmp_path)
    _save_case(client, "SLAB", {"value": 1})
    wt = _save_case(client, "WT", {"value": 2}).json()

    patched = client.patch(f"/api/v1/saved-typed-values/{wt['id']}", json={"make_default": True})
    assert patched.status_code == 200
    assert patched.json()["is_default"] is True

    by_name = {record["name"]: record for record in client.get("/api/v1/saved-typed-values").json()}
    assert by_name["WT"]["is_default"] is True
    assert by_name["SLAB"]["is_default"] is False

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_library_multiple_flag_is_authoritative(tmp_path: Path):
    client = _client(tmp_path)
    # A library type marked multiple allows several cases even when the save request's
    # own type_schema omits the flag (the live library wins over the frozen schema).
    put = client.put("/api/v1/type-library/LibRule", json={"fields": {"value": {"type": "integer"}}, "multiple": True})
    assert put.status_code == 200, put.text

    plain_schema = {"name": "LibRule", "fields": [{"name": "value", "type": "integer", "container": "single", "required": True, "options": []}]}
    first = client.post(
        "/api/v1/saved-typed-values",
        json={"type_key": "LibRule", "container": "single", "name": "A", "type_schema": plain_schema, "value": {"value": 1}},
    )
    second = client.post(
        "/api/v1/saved-typed-values",
        json={"type_key": "LibRule", "container": "single", "name": "B", "type_schema": plain_schema, "value": {"value": 2}},
    )
    assert first.status_code == 201 and second.status_code == 201, second.text
    listed = client.get("/api/v1/saved-typed-values").json()
    assert len(listed) == 2
    assert all(record["multiple"] for record in listed)

    app.dependency_overrides.clear()
    get_runtime.cache_clear()
