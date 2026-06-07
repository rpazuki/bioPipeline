from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_runtime
from app.main import app
from app.services.runtime import create_runtime

VALID = """
job: growth_full
stages:
  - name: only
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out
"""

BASE = "/api/v1/job-definition-store"


def _client(tmp_path: Path) -> TestClient:
    app.dependency_overrides.clear()
    get_runtime.cache_clear()
    app.dependency_overrides[get_runtime] = lambda: create_runtime(tmp_path)
    return TestClient(app)


def _reset():
    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_save_list_get_and_tree(tmp_path: Path):
    client = _client(tmp_path)

    save = client.post(BASE, json={"name": "designs/growth.yaml", "content": VALID, "overwrite": True})
    assert save.status_code == 201
    assert save.json()["job"] == "growth_full"

    listing = client.get(BASE)
    assert listing.status_code == 200
    assert listing.json() == [{"name": "designs/growth.yaml", "job": "growth_full", "is_valid": True, "error": None}]

    doc = client.get(f"{BASE}/designs/growth.yaml")
    assert doc.status_code == 200
    assert doc.json()["content"] == VALID

    tree = client.get(f"{BASE}/tree")
    assert tree.status_code == 200
    assert tree.json()[0]["path"] == "designs"
    assert tree.json()[0]["children"][0]["path"] == "designs/growth.yaml"
    assert tree.json()[0]["children"][0]["job"] == "growth_full"
    _reset()


def test_save_invalid_returns_400(tmp_path: Path):
    client = _client(tmp_path)
    response = client.post(BASE, json={"name": "bad.yaml", "content": "job: x\n", "overwrite": True})
    assert response.status_code == 400
    _reset()


def test_archive_restore_and_archived_list(tmp_path: Path):
    client = _client(tmp_path)
    client.post(BASE, json={"name": "growth.yaml", "content": VALID, "overwrite": True})

    assert client.post(f"{BASE}/growth.yaml/archive").status_code == 204
    assert client.get(BASE).json() == []  # gone from active
    archived = client.get(f"{BASE}/archived").json()
    assert [a["name"] for a in archived] == ["growth.yaml"]

    restore = client.post(f"{BASE}/growth.yaml/restore")
    assert restore.status_code == 200
    assert [s["name"] for s in client.get(BASE).json()] == ["growth.yaml"]
    assert client.get(f"{BASE}/archived").json() == []
    _reset()


def test_delete_and_404s(tmp_path: Path):
    client = _client(tmp_path)
    client.post(BASE, json={"name": "growth.yaml", "content": VALID, "overwrite": True})

    assert client.delete(f"{BASE}/growth.yaml").status_code == 204
    assert client.get(f"{BASE}/growth.yaml").status_code == 404
    assert client.post(f"{BASE}/missing.yaml/archive").status_code == 404
    assert client.post(f"{BASE}/missing.yaml/restore").status_code == 404
    _reset()
