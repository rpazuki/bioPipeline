from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_runtime
from app.main import app
from app.services.runtime import create_runtime
from bio_pipeline_manager.auth_service import hash_session_token
from bio_pipeline_manager.models import utc_now


def test_renew_session_extends_expiry(tmp_path: Path):
    runtime = create_runtime(tmp_path, auth_session_ttl_hours=1.0)
    runtime.auth.bootstrap_admin(username="admin", password="password123")
    result = runtime.auth.authenticate(username="admin", password="password123")

    # A freshly issued session still has most of its TTL left.
    assert runtime.auth.should_renew(result.session) is False

    # Age it to just under the renewal threshold (half of a 1h TTL).
    near_expiry = utc_now() + timedelta(minutes=5)
    runtime.auth.store.touch_session(result.session.id, expires_at=near_expiry)
    aged = runtime.auth.store.get_session(result.session.id)
    assert runtime.auth.should_renew(aged) is True

    renewed = runtime.auth.renew_session(aged)
    assert renewed.expires_at > near_expiry
    assert runtime.auth.should_renew(renewed) is False


def test_request_near_expiry_refreshes_cookie(tmp_path: Path):
    app.dependency_overrides.clear()
    get_runtime.cache_clear()
    runtime = create_runtime(tmp_path, auth_session_ttl_hours=1.0)
    app.dependency_overrides[get_runtime] = lambda: runtime
    try:
        runtime.auth.bootstrap_admin(username="admin", password="password123")
        client = TestClient(app)
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "password123"},
            ).status_code
            == 200
        )

        token = client.cookies["bio_pipeline_session"]
        session = runtime.auth.store.get_session_by_token_hash(hash_session_token(token))
        before = session.expires_at

        # A normal request well inside the TTL does not re-issue the cookie.
        fresh = client.get("/api/v1/auth/me")
        assert fresh.status_code == 200
        assert "set-cookie" not in {k.lower() for k in fresh.headers}

        # Age the session past the halfway point; the next request renews it and
        # re-issues the cookie.
        runtime.auth.store.touch_session(
            session.id, expires_at=utc_now() + timedelta(minutes=5)
        )
        renewed = client.get("/api/v1/auth/me")
        assert renewed.status_code == 200
        assert "bio_pipeline_session" in renewed.headers.get("set-cookie", "")

        after = runtime.auth.store.get_session_by_token_hash(
            hash_session_token(token)
        ).expires_at
        assert after > before
    finally:
        app.dependency_overrides.clear()
        get_runtime.cache_clear()
