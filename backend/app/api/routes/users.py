from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime, require_admin
from app.api.routes.auth import user_response
from app.schemas.pipelines import PasswordResetRequest, UserCreateRequest, UserResponse, UserUpdateRequest
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.auth_models import Role, UserRecord
from bio_pipeline_manager.auth_service import AuthError

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_admin)])


def _role(value: str) -> Role:
    try:
        return Role(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role must be 'admin' or 'user'") from exc


def _ensure_not_last_admin(runtime: PipelineRuntime, user_id: str, *, role: Role | None, is_active: bool | None) -> None:
    current = runtime.auth.get_user(user_id)
    would_stop_being_active_admin = current.role == Role.ADMIN and (
        role == Role.USER or is_active is False
    )
    if not would_stop_being_active_admin:
        return
    active_admins = [
        user for user in runtime.auth.list_users()
        if user.id != user_id and user.role == Role.ADMIN and user.is_active
    ]
    if not active_admins:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the last active admin",
        )


@router.get("", response_model=list[UserResponse])
async def list_users(runtime: Annotated[PipelineRuntime, Depends(get_runtime)]) -> list[UserResponse]:
    return [user_response(user) for user in runtime.auth.list_users()]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> UserResponse:
    try:
        user = runtime.auth.create_user(
            username=body.username,
            display_name=body.display_name,
            password=body.password,
            role=_role(body.role),
            is_active=body.is_active,
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return user_response(user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> UserResponse:
    try:
        return user_response(runtime.auth.get_user(user_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> UserResponse:
    role = _role(body.role) if body.role is not None else None
    try:
        _ensure_not_last_admin(runtime, user_id, role=role, is_active=body.is_active)
        user = runtime.auth.update_user(
            user_id,
            username=body.username,
            display_name=body.display_name,
            role=role,
            is_active=body.is_active,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return user_response(user)


@router.post("/{user_id}/reset-password", response_model=UserResponse)
async def reset_password(
    user_id: str,
    body: PasswordResetRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> UserResponse:
    try:
        return user_response(runtime.auth.reset_password(user_id, body.password))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{user_id}/disable", response_model=UserResponse)
async def disable_user(
    user_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> UserResponse:
    try:
        _ensure_not_last_admin(runtime, user_id, role=None, is_active=False)
        return user_response(runtime.auth.disable_user(user_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc


@router.post("/{user_id}/enable", response_model=UserResponse)
async def enable_user(
    user_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> UserResponse:
    try:
        return user_response(runtime.auth.enable_user(user_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
