from __future__ import annotations

from datetime import datetime, timezone

from app.api.deps import require_admin, require_authenticated_user
from bio_pipeline_manager.auth_models import Role, UserRecord


def install_admin_override(app) -> None:
    now = datetime.now(timezone.utc)

    def _admin() -> UserRecord:
        return UserRecord(
            id="test-admin",
            username="admin",
            display_name="Test Admin",
            password_hash="unused",
            role=Role.ADMIN,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

    app.dependency_overrides[require_admin] = _admin


def install_user_override(app, *, user_id: str = "test-user") -> None:
    now = datetime.now(timezone.utc)

    def _user() -> UserRecord:
        return UserRecord(
            id=user_id,
            username="user",
            display_name="Test User",
            password_hash="unused",
            role=Role.USER,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

    app.dependency_overrides[require_authenticated_user] = _user
