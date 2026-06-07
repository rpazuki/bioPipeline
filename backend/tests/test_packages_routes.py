import dataclasses
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_runtime
from app.main import app
from app.services.runtime import create_runtime
from bio_pipeline_manager.auth_models import Role
from bio_pipeline_manager.models import JobSpec
from bio_pipeline_manager.packages import InstallStore, PackageManager


def _runtime_with_fake_pip(tmp_path: Path, code: int = 0, out: str = "ok", err: str = ""):
    rt = create_runtime(tmp_path)

    def fake(python_executable: str, args: list[str]):
        return code, out, err

    packages = PackageManager(
        InstallStore(tmp_path / "installs.sqlite"),
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


def test_requires_authenticated_admin(tmp_path: Path):
    runtime = _runtime_with_fake_pip(tmp_path)
    client = _use(runtime)

    assert client.get("/api/v1/packages").status_code == 401

    runtime.auth.create_user(username="worker", password="password123", role=Role.USER)
    login = client.post("/api/v1/auth/login", json={"username": "worker", "password": "password123"})
    assert login.status_code == 200
    assert client.get("/api/v1/packages").status_code == 403
    _reset()


def test_list_install_and_history(tmp_path: Path):
    runtime = _runtime_with_fake_pip(tmp_path)
    client = _use(runtime)
    _login_admin(client, runtime)

    listing = client.get("/api/v1/packages")
    assert listing.status_code == 200
    assert any(p["name"].lower() == "pytest" for p in listing.json()["installed"])

    install = client.post(
        "/api/v1/packages/install",
        json={"spec": "pytest", "source_type": "pypi"},
    )
    assert install.status_code == 200
    assert install.json()["ok"] is True
    assert install.json()["action"] == "install"

    history = client.get("/api/v1/packages").json()["history"]
    assert len(history) >= 1
    assert history[0]["actor"] == "api"
    _reset()


def test_install_refused_while_jobs_running(tmp_path: Path):
    runtime = _runtime_with_fake_pip(tmp_path)
    job = runtime.job_store.create_job(
        JobSpec(yaml_path=tmp_path / "p.yaml", pipeline_name="demo", output_dir=tmp_path / "o"),
        tmp_path / "logs" / "j.log",
    )
    runtime.job_store.claim_job(job.id)  # QUEUED -> RUNNING

    client = _use(runtime)
    _login_admin(client, runtime)
    response = client.post(
        "/api/v1/packages/install",
        json={"spec": "pytest"},
    )
    assert response.status_code == 409
    _reset()


def test_bad_source_type_returns_400(tmp_path: Path):
    runtime = _runtime_with_fake_pip(tmp_path)
    client = _use(runtime)
    _login_admin(client, runtime)
    response = client.post(
        "/api/v1/packages/install",
        json={"spec": "x", "source_type": "moonbeam"},
    )
    assert response.status_code == 400
    _reset()
