from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime, require_authenticated_user
from app.schemas.pipelines import (
    SavedTypedValueResponse,
    SavedTypedValueUpdateRequest,
    SavedTypedValueUpsertRequest,
)
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.auth_models import UserRecord
from bio_pipeline_manager.typed_value_store import _UNSET, SavedTypedValueRecord

# Per-researcher reusable values for typed and explicitly saveable plain fields.
# Available to any authenticated user; every value is scoped to the caller.
router = APIRouter(prefix="/saved-typed-values", tags=["saved-typed-values"])


def _resolve_multiple(
    library: dict[str, Any], type_key: str, type_schema: dict[str, Any], value_kind: str
) -> bool:
    """Whether ``type_key`` allows several named cases.

    Plain (non-typed) values are never multi-instance. For a typed value the live
    library is authoritative; a type that is no longer in the library (inline or
    deleted) falls back to the ``multiple`` flag frozen onto its resolved schema.
    """
    if value_kind == "plain":
        return False
    entry = library.get(type_key)
    if isinstance(entry, dict):
        return bool(entry.get("multiple"))
    return bool((type_schema or {}).get("multiple"))


@router.get("", response_model=list[SavedTypedValueResponse])
async def list_saved_typed_values(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> list[SavedTypedValueResponse]:
    library = runtime.type_library.all()
    return [
        _response(record, _resolve_multiple(library, record.type_key, record.type_schema, record.value_kind))
        for record in runtime.typed_values.list(user.id)
    ]


@router.post("", response_model=SavedTypedValueResponse, status_code=status.HTTP_201_CREATED)
async def upsert_saved_typed_value(
    body: SavedTypedValueUpsertRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> SavedTypedValueResponse:
    type_key = body.type_key.strip()
    if not type_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A type key is required")
    multiple = _resolve_multiple(runtime.type_library.all(), type_key, body.type_schema, body.value_kind)
    # A single-instance type keeps one value (name forced empty, always overwritten);
    # a multi-instance type needs a name to distinguish its cases.
    name = body.name.strip() if multiple else ""
    if multiple and not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A case name is required")
    record = runtime.typed_values.upsert(
        user_id=user.id,
        type_key=type_key,
        container=body.container,
        name=name,
        make_default=body.make_default,
        label=body.label or name or type_key,
        type_schema=body.type_schema,
        value_kind=body.value_kind,
        field_schema=body.field_schema,
        value=body.value,
    )
    return _response(record, multiple)


@router.patch("/{record_id}", response_model=SavedTypedValueResponse)
async def update_saved_typed_value(
    record_id: str,
    body: SavedTypedValueUpdateRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> SavedTypedValueResponse:
    record = _get_owned(runtime, record_id, user.id)
    multiple = _resolve_multiple(
        runtime.type_library.all(), record.type_key, record.type_schema, record.value_kind
    )
    # Renaming only applies to multi-instance types; a single-instance case stays "".
    rename = body.name if multiple else None
    # Distinguish "value omitted" (leave it) from an explicit null the researcher saved.
    value = body.value if "value" in body.model_fields_set else _UNSET
    try:
        updated = runtime.typed_values.update(
            record_id, value=value, label=body.label, name=rename, make_default=body.make_default
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _response(updated, multiple)


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


def _response(record: SavedTypedValueRecord, multiple: bool) -> SavedTypedValueResponse:
    return SavedTypedValueResponse(
        id=record.id,
        type_key=record.type_key,
        container=record.container,
        name=record.name,
        is_default=record.is_default,
        multiple=multiple,
        label=record.label,
        type_schema=record.type_schema,
        value_kind=record.value_kind,
        field_schema=record.field_schema,
        value=record.value,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
