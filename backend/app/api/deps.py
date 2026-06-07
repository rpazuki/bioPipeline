from __future__ import annotations

from typing import Annotated
from functools import lru_cache

from fastapi import Cookie, Depends, HTTPException, status

from app.core.config import settings
from app.services.runtime import PipelineRuntime, create_runtime
from bio_pipeline_manager.auth_models import Role, UserRecord


@lru_cache
def get_runtime() -> PipelineRuntime:
    return create_runtime(
        settings.pipeline_home,
        auth_session_ttl_hours=settings.auth_session_ttl_hours,
    )


def get_current_user(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    session_token: Annotated[str | None, Cookie(alias=settings.auth_session_cookie_name)] = None,
) -> UserRecord:
    resolved = runtime.auth.user_for_token(session_token)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    user, _session = resolved
    return user


def require_authenticated_user(
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> UserRecord:
    return user


def require_admin(user: Annotated[UserRecord, Depends(get_current_user)]) -> UserRecord:
    if user.role != Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user
