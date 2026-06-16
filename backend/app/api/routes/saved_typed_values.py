from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime, require_authenticated_user
from app.schemas.pipelines import (
    SavedTypedValueResponse,
    SavedTypedValueUpdateRequest,
    SavedTypedValueUpsertRequest,
)
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.auth_models import UserRecord
from bio_pipeline_manager.typed_value_store import SavedTypedValueRecord

# Per-researcher reusable values for typed and explicitly saveable plain fields.
# Available to any authenticated user; every value is scoped to the caller.
router = APIRouter(prefix="/saved-typed-values", tags=["saved-typed-values"])


@router.get("", response_model=list[SavedTypedValueResponse])
async def list_saved_typed_values(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> list[SavedTypedValueResponse]:
    return [_response(record) for record in runtime.typed_values.list(user.id)]


@router.post("", response_model=SavedTypedValueResponse, status_code=status.HTTP_201_CREATED)
async def upsert_saved_typed_value(
    body: SavedTypedValueUpsertRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> SavedTypedValueResponse:
    type_key = body.type_key.strip()
    if not type_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A type key is required")
    record = runtime.typed_values.upsert(
        user_id=user.id,
        type_key=type_key,
        container=body.container,
        label=body.label or type_key,
        type_schema=body.type_schema,
        value_kind=body.value_kind,
        field_schema=body.field_schema,
        value=body.value,
    )
    return _response(record)


@router.patch("/{record_id}", response_model=SavedTypedValueResponse)
async def update_saved_typed_value(
    record_id: str,
    body: SavedTypedValueUpdateRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> SavedTypedValueResponse:
    _get_owned(runtime, record_id, user.id)
    record = runtime.typed_values.update(record_id, value=body.value, label=body.label)
    return _response(record)


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_typed_value(
    record_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> None:
    _get_owned(runtime, record_id, user.id)
    runtime.typed_values.delete(record_id)


def _get_owned(runtime: PipelineRuntime, record_id: str, user_id: str) -> SavedTypedValueRecord:
    try:
        record = runtime.typed_values.get(record_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if record.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved value not found")
    return record


def _response(record: SavedTypedValueRecord) -> SavedTypedValueResponse:
    return SavedTypedValueResponse(
        id=record.id,
        type_key=record.type_key,
        container=record.container,
        label=record.label,
        type_schema=record.type_schema,
        value_kind=record.value_kind,
        field_schema=record.field_schema,
        value=record.value,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
