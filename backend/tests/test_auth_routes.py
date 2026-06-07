from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_runtime
from app.main import app
from app.services.runtime import create_runtime
from bio_pipeline_manager.auth_models import Role


def _client(tmp_path: Path):
    app.dependency_overrides.clear()
    get_runtime.cache_clear()
    runtime = create_runtime(tmp_path)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app), runtime


def _reset():
    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def _login(client: TestClient, username: str, password: str = "password123"):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_login_me_and_logout(tmp_path: Path):
    client, runtime = _client(tmp_path)
    runtime.auth.bootstrap_admin(username="admin", password="password123")

    assert client.get("/api/v1/auth/me").status_code == 401

    login = _login(client, "admin")
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "admin"
    assert "bio_pipeline_session" in client.cookies

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "admin"

    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    _reset()


def test_admin_routes_require_admin_role(tmp_path: Path):
    client, runtime = _client(tmp_path)

    assert client.get("/api/v1/runtime").status_code == 401

    runtime.auth.create_user(username="worker", password="password123", role=Role.USER)
    assert _login(client, "worker").status_code == 200
    assert client.get("/api/v1/runtime").status_code == 403

    assert client.post("/api/v1/auth/logout").status_code == 204
    runtime.auth.bootstrap_admin(username="admin", password="password123")
    assert _login(client, "admin").status_code == 200
    assert client.get("/api/v1/runtime").status_code == 200
    _reset()


def test_admin_user_management_disable_only(tmp_path: Path):
    client, runtime = _client(tmp_path)
    runtime.auth.bootstrap_admin(username="admin", password="password123")
    assert _login(client, "admin").status_code == 200

    create = client.post(
        "/api/v1/users",
        json={"username": "worker", "password": "password123", "role": "user"},
    )
    assert create.status_code == 201
    user_id = create.json()["id"]

    listing = client.get("/api/v1/users")
    assert [user["username"] for user in listing.json()] == ["admin", "worker"]

    disable = client.post(f"/api/v1/users/{user_id}/disable")
    assert disable.status_code == 200
    assert disable.json()["is_active"] is False

    assert client.post("/api/v1/auth/logout").status_code == 204
    assert _login(client, "worker").status_code == 401

    assert _login(client, "admin").status_code == 200
    enable = client.post(f"/api/v1/users/{user_id}/enable")
    assert enable.status_code == 200
    assert enable.json()["is_active"] is True

    reset = client.post(f"/api/v1/users/{user_id}/reset-password", json={"password": "newpass123"})
    assert reset.status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert _login(client, "worker", "newpass123").status_code == 200
    _reset()


def test_cannot_remove_last_active_admin(tmp_path: Path):
    client, runtime = _client(tmp_path)
    runtime.auth.bootstrap_admin(username="admin", password="password123")
    assert _login(client, "admin").status_code == 200
    admin_id = runtime.auth.store.get_user_by_username("admin").id

    disable = client.post(f"/api/v1/users/{admin_id}/disable")
    assert disable.status_code == 400
    assert "last active admin" in disable.json()["detail"]

    demote = client.patch(f"/api/v1/users/{admin_id}", json={"role": "user"})
    assert demote.status_code == 400
    assert "last active admin" in demote.json()["detail"]
    _reset()
