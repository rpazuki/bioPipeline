from __future__ import annotations

from typing import Annotated
from functools import lru_cache

from fastapi import Cookie, Depends, HTTPException, Response, status

from app.core.config import settings
from app.services.runtime import PipelineRuntime, create_runtime
from bio_pipeline_manager.auth_models import Role, UserRecord


@lru_cache
def get_runtime() -> PipelineRuntime:
    return create_runtime(
        settings.pipeline_home,
        auth_session_ttl_hours=settings.auth_session_ttl_hours,
        shared_roots=settings.shared_roots,
        upload_max_bytes=settings.upload_max_bytes,
        task_timeout=settings.task_timeout_seconds,
    )


def set_session_cookie(response: Response, token: str) -> None:
    """Write the session cookie with the standard attributes.

    Shared by login and sliding-expiration renewal so both stay in lock-step on
    max-age, security flags, and path.
    """
    response.set_cookie(
        settings.auth_session_cookie_name,
        token,
        max_age=int(settings.auth_session_ttl_hours * 60 * 60),
        httponly=True,
        secure=settings.auth_secure_cookies,
        samesite="lax",
        path="/",
    )


def get_current_user(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    response: Response,
    session_token: Annotated[str | None, Cookie(alias=settings.auth_session_cookie_name)] = None,
) -> UserRecord:
    resolved = runtime.auth.user_for_token(session_token)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    user, session = resolved
    # Sliding expiration: refresh an active session (and its cookie) once it is
    # past the halfway point of its TTL. Without this, a session dies at a fixed
    # TTL even during active use, so background polls start returning 401 while a
    # long-running request admitted earlier still completes — exactly the
    # "ai-chat 200 but jobs 401" split that motivated this change.
    if session_token and runtime.auth.should_renew(session):
        runtime.auth.renew_session(session)
        set_session_cookie(response, session_token)
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
