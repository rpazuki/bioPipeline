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
