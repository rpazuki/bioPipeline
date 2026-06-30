import dataclasses
import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_runtime
from app.main import app
from app.services.runtime import create_runtime
from bio_pipeline_manager.auth_models import Role
from bio_pipeline_manager.packages import InstallStore, PackageManager

PIPELINE = """
pipelines:
  - demo:
      Inputs: []
      Processes: []
      Outputs: []
"""

JOB_DEF = """
job: growth_full
stages:
  - name: only
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out
"""

FIELDS = [
    {
        "id": "f1",
        "label": "F1",
        "type": "string",
        "bindings": [{"target": "definition_path", "path": ["defaults", "x"]}],
    }
]


def _runtime_with_fake_pip(home):
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    rt = create_runtime(home)

    def fake(python_executable: str, args: list[str]):
        return 0, "ok", ""

    packages = PackageManager(
        InstallStore(home / "installs.sqlite"),
        pip_runner=fake,
        job_guard=rt.job_store.has_active_jobs,
    )
    return dataclasses.replace(rt, packages=packages)


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
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "password123"})
    assert response.status_code == 200


def _seed(runtime) -> None:
    runtime.yaml_store.save("demo.yaml", PIPELINE)
    runtime.definition_store.save("job1.yaml", JOB_DEF)
    runtime.published_jobs.create(
        name="Pub A", description="d", definition_name="job1.yaml",
        definition_content=JOB_DEF, fields=FIELDS, actor="admin", status="published",
    )
    runtime.packages.install("pytest", source_type="pypi", actor="admin")


def test_export_requires_admin(tmp_path: Path):
    runtime = _runtime_with_fake_pip(tmp_path)
    client = _use(runtime)
    assert client.get("/api/v1/backup/export").status_code == 401

    runtime.auth.create_user(username="worker", password="password123", role=Role.USER)
    client.post("/api/v1/auth/login", json={"username": "worker", "password": "password123"})
    assert client.get("/api/v1/backup/export").status_code == 403
    _reset()


def test_export_returns_zip(tmp_path: Path):
    runtime = _runtime_with_fake_pip(tmp_path)
    _seed(runtime)
    client = _use(runtime)
    _login_admin(client, runtime)

    response = client.get("/api/v1/backup/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers.get("content-disposition", "")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
    assert {"manifest.json", "pipelines/demo.yaml", "job_definitions/job1.yaml", "requirements.txt"} <= names
    _reset()


def test_import_round_trip(tmp_path: Path):
    src = _runtime_with_fake_pip(tmp_path / "a")
    _seed(src)
    client_a = _use(src)
    _login_admin(client_a, src)
    blob = client_a.get("/api/v1/backup/export").content

    dst = _runtime_with_fake_pip(tmp_path / "b")
    client_b = _use(dst)
    _login_admin(client_b, dst)
    response = client_b.post(
        "/api/v1/backup/import?overwrite=false&install_packages=true",
        content=blob,
        headers={"Content-Type": "application/zip"},
    )
    assert response.status_code == 200
    report = response.json()
    assert report["pipelines"]["created"] == ["demo.yaml"]
    assert report["job_definitions"]["created"] == ["job1.yaml"]
    assert report["published_jobs"]["created"] == ["Pub A"]
    assert report["packages"]["attempted"] is True and report["packages"]["ok"] is True

    assert dst.yaml_store.load("demo.yaml") == PIPELINE
    assert {r.name for r in dst.published_jobs.list()} == {"Pub A"}
    _reset()


def test_import_rejects_garbage(tmp_path: Path):
    runtime = _runtime_with_fake_pip(tmp_path)
    client = _use(runtime)
    _login_admin(client, runtime)
    response = client.post(
        "/api/v1/backup/import",
        content=b"not a zip",
        headers={"Content-Type": "application/zip"},
    )
    assert response.status_code == 400
    _reset()
