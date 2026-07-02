from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_runtime
from app.main import app
from app.services.runtime import create_runtime

RULE = {
    "description": "rule",
    "fields": {
        "direction": {"type": "enum", "options": ["alphabetical", "numerical"], "required": False},
        "sample_size": {"type": "integer", "required": False},
    },
}


def _use(runtime):
    app.dependency_overrides.clear()
    get_runtime.cache_clear()
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def _reset():
    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def _login_admin(client: TestClient, runtime) -> None:
    runtime.auth.bootstrap_admin(username="admin", password="password123")
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "password123"}).status_code == 200


def test_requires_admin(tmp_path: Path):
    runtime = create_runtime(tmp_path)
    client = _use(runtime)
    assert client.get("/api/v1/type-library").status_code == 401
    _reset()


def test_upsert_list_get_delete(tmp_path: Path):
    runtime = create_runtime(tmp_path)
    client = _use(runtime)
    _login_admin(client, runtime)

    put = client.put("/api/v1/type-library/CustomReplicateRule", json=RULE)
    assert put.status_code == 200
    assert put.json()["name"] == "CustomReplicateRule"

    listing = client.get("/api/v1/type-library")
    assert [t["name"] for t in listing.json()["types"]] == ["CustomReplicateRule"]

    one = client.get("/api/v1/type-library/CustomReplicateRule")
    assert one.json()["fields"]["sample_size"]["type"] == "integer"

    assert client.delete("/api/v1/type-library/CustomReplicateRule").status_code == 204
    assert client.get("/api/v1/type-library").json()["types"] == []
    _reset()


def test_upsert_rejects_unknown_reference(tmp_path: Path):
    runtime = create_runtime(tmp_path)
    client = _use(runtime)
    _login_admin(client, runtime)

    bad = client.put("/api/v1/type-library/Policy", json={"fields": {"rule": {"type": "Ghost"}}})
    assert bad.status_code == 400
    assert "unknown type" in bad.json()["detail"]
    _reset()


def test_get_missing_type_returns_404(tmp_path: Path):
    runtime = create_runtime(tmp_path)
    client = _use(runtime)
    _login_admin(client, runtime)
    assert client.get("/api/v1/type-library/Nope").status_code == 404
    _reset()


def test_extract_from_python_class_then_upsert(tmp_path: Path):
    runtime = create_runtime(tmp_path)
    client = _use(runtime)
    _login_admin(client, runtime)

    extracted = client.post(
        "/api/v1/type-library/extract",
        json={"qualified_name": "labUtils.media_bot.CustomReplicateRule"},
    )
    assert extracted.status_code == 200
    payload = extracted.json()
    assert payload["root"] == "CustomReplicateRule"
    rule = payload["types"]["CustomReplicateRule"]

    # The extracted entry upserts cleanly into the library.
    put = client.put("/api/v1/type-library/CustomReplicateRule", json=rule)
    assert put.status_code == 200
    assert "direction" in put.json()["fields"]
    _reset()


def test_extract_non_structured_returns_400(tmp_path: Path):
    runtime = create_runtime(tmp_path)
    client = _use(runtime)
    _login_admin(client, runtime)
    bad = client.post("/api/v1/type-library/extract", json={"qualified_name": "math.sqrt"})
    assert bad.status_code == 400
    _reset()


TYPED_JOB_DEF = """
job: typed_demo
stages:
  - name: s1
    pipeline: p
    pipeline_yaml: x.yaml
    output_dir: out
""".strip()


def test_editing_a_type_refreshes_referencing_published_jobs(tmp_path: Path):
    runtime = create_runtime(tmp_path)
    client = _use(runtime)
    _login_admin(client, runtime)

    # The type is published with sample_size *required*; a job freezes that schema.
    required_rule = {
        "description": "rule",
        "fields": {
            "direction": {"type": "enum", "options": ["alphabetical", "numerical"], "required": False},
            "sample_size": {"type": "integer", "required": True},
        },
    }
    assert client.put("/api/v1/type-library/CustomReplicateRule", json=required_rule).status_code == 200

    create = client.post(
        "/api/v1/published-jobs/admin",
        json={
            "name": "Typed demo",
            "definition_name": "typed_demo.yaml",
            "definition_content": TYPED_JOB_DEF,
            "status": "published",
            "fields": [
                {
                    "id": "custom_rules",
                    "label": "Custom rules",
                    "type": "typed",
                    "schema_ref": "CustomReplicateRule",
                    "container": "map",
                    "bindings": [
                        {
                            "target": "stage_process_arg",
                            "stage": "s1",
                            "process": "df_replicate_stats",
                            "parameter": "custom_rules",
                        }
                    ],
                }
            ],
        },
    )
    assert create.status_code == 201, create.text
    job_id = create.json()["id"]

    def sample_size_required() -> bool:
        job = client.get(f"/api/v1/published-jobs/admin/{job_id}").json()
        [field] = [f for f in job["fields"] if f.get("schema_ref") == "CustomReplicateRule"]
        [inner] = [n for n in field["type_schema"]["fields"] if n["name"] == "sample_size"]
        return inner["required"]

    assert sample_size_required() is True

    # Marking sample_size optional in the library must propagate to the published job,
    # not just to jobs published afterwards.
    optional_rule = {
        **required_rule,
        "fields": {**required_rule["fields"], "sample_size": {"type": "integer", "required": False}},
    }
    assert client.put("/api/v1/type-library/CustomReplicateRule", json=optional_rule).status_code == 200

    assert sample_size_required() is False
    _reset()


def test_multiple_flag_round_trips_and_resolves(tmp_path: Path):
    runtime = create_runtime(tmp_path)
    client = _use(runtime)
    _login_admin(client, runtime)

    put = client.put("/api/v1/type-library/CustomReplicateRule", json={**RULE, "multiple": True})
    assert put.status_code == 200
    assert put.json()["multiple"] is True
    assert client.get("/api/v1/type-library/CustomReplicateRule").json()["multiple"] is True
    assert client.get("/api/v1/type-library").json()["types"][0]["multiple"] is True

    # The flag flows into a bound field's resolved schema so the researcher UI can act on it.
    create = client.post(
        "/api/v1/published-jobs/admin",
        json={
            "name": "Typed demo",
            "definition_name": "typed_demo.yaml",
            "definition_content": TYPED_JOB_DEF,
            "status": "published",
            "fields": [
                {
                    "id": "custom_rules",
                    "label": "Custom rules",
                    "type": "typed",
                    "schema_ref": "CustomReplicateRule",
                    "container": "map",
                    "bindings": [
                        {"target": "stage_process_arg", "stage": "s1", "process": "df_replicate_stats", "parameter": "custom_rules"}
                    ],
                }
            ],
        },
    )
    assert create.status_code == 201, create.text
    job = client.get(f"/api/v1/published-jobs/admin/{create.json()['id']}").json()
    [field] = [f for f in job["fields"] if f.get("schema_ref") == "CustomReplicateRule"]
    assert field["type_schema"]["multiple"] is True
    _reset()
