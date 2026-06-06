from __future__ import annotations

import secrets
from functools import lru_cache

from fastapi import Header, HTTPException, status

from app.core.config import settings
from app.services.runtime import PipelineRuntime, create_runtime


@lru_cache
def get_runtime() -> PipelineRuntime:
    return create_runtime(settings.pipeline_home)


def require_package_admin(authorization: str | None = Header(default=None)) -> None:
    """Gate the package-management endpoints behind a bearer admin token.

    When no token is configured the feature is disabled (503), so the install
    surface is never anonymously reachable by default.
    """
    token = settings.package_admin_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Package management is disabled (no admin token configured)",
        )
    expected = f"Bearer {token}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin token",
        )

