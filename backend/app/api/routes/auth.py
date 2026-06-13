from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from app.api.deps import get_current_user, get_runtime, set_session_cookie
from app.core.config import settings
from app.schemas.pipelines import AuthResponse, ChangePasswordRequest, LoginRequest, UserResponse
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.auth_models import UserRecord
from bio_pipeline_manager.auth_service import AuthError

router = APIRouter(prefix="/auth", tags=["auth"])


def user_response(user: UserRecord) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    response: Response,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> AuthResponse:
    try:
        result = runtime.auth.authenticate(username=body.username, password=body.password)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    set_session_cookie(response, result.token)
    return AuthResponse(user=user_response(result.user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    session_token: Annotated[str | None, Cookie(alias=settings.auth_session_cookie_name)] = None,
) -> None:
    runtime.auth.logout(session_token)
    response.delete_cookie(settings.auth_session_cookie_name, path="/")


@router.get("/me", response_model=AuthResponse)
async def me(user: Annotated[UserRecord, Depends(get_current_user)]) -> AuthResponse:
    return AuthResponse(user=user_response(user))


@router.post("/change-password", response_model=AuthResponse)
async def change_password(
    body: ChangePasswordRequest,
    user: Annotated[UserRecord, Depends(get_current_user)],
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> AuthResponse:
    try:
        updated = runtime.auth.change_password(
            user.id,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AuthResponse(user=user_response(updated))
