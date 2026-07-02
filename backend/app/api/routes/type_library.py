from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime, require_admin
from app.schemas.pipelines import (
    TypeDefRequest,
    TypeDefResponse,
    TypeExtractRequest,
    TypeExtractResponse,
    TypeLibraryResponse,
)
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.auth_models import UserRecord
from bio_pipeline_manager.published_jobs import refresh_typed_field_schemas
from bio_pipeline_manager.type_extract import TypeExtractError, extract_type
from bio_pipeline_manager.type_schema import TypeSchemaError

# The project-level type library is managed on the Environment page (admin-only),
# alongside the Python packages the types are usually extracted from.
router = APIRouter(prefix="/type-library", tags=["type-library"], dependencies=[Depends(require_admin)])


def _response(name: str, type_def: dict[str, Any]) -> TypeDefResponse:
    return TypeDefResponse(
        name=name,
        description=str(type_def.get("description", "") or ""),
        fields=type_def.get("fields") or {},
        type=str(type_def.get("type", "") or ""),
        options=type_def.get("options") or [],
        default=type_def.get("default"),
        source=str(type_def.get("source", "") or ""),
        multiple=bool(type_def.get("multiple", False)),
    )


@router.get("", response_model=TypeLibraryResponse)
async def list_types(runtime: Annotated[PipelineRuntime, Depends(get_runtime)]) -> TypeLibraryResponse:
    library = runtime.type_library.all()
    return TypeLibraryResponse(types=[_response(name, library[name]) for name in sorted(library)])


@router.post("/extract", response_model=TypeExtractResponse)
async def extract(
    body: TypeExtractRequest,
    _runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> TypeExtractResponse:
    """Introspect a Python class (e.g. ``labUtils.media_bot.CustomReplicateRule``).

    Returns library-ready type entries for preview; the caller upserts the ones it
    wants via ``PUT /type-library/{name}``.
    """
    try:
        result = extract_type(body.qualified_name)
    except (TypeExtractError, TypeSchemaError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TypeExtractResponse(**result)


@router.get("/{name}", response_model=TypeDefResponse)
async def get_type(
    name: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> TypeDefResponse:
    try:
        return _response(name, runtime.type_library.get(name))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Type '{name}' not found") from exc


@router.put("/{name}", response_model=TypeDefResponse)
async def upsert_type(
    name: str,
    body: TypeDefRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    admin: Annotated[UserRecord, Depends(require_admin)],
) -> TypeDefResponse:
    try:
        stored = runtime.type_library.upsert(name, body.model_dump())
    except TypeSchemaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    # Editing a type changes the resolved schema frozen onto every published job that
    # references it; refresh those copies so already-published jobs track the edit.
    refresh_typed_field_schemas(runtime.published_jobs, runtime.type_library.all(), actor=admin.id)
    return _response(name, stored)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_type(
    name: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    admin: Annotated[UserRecord, Depends(require_admin)],
) -> None:
    try:
        runtime.type_library.delete(name)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Type '{name}' not found") from exc
    except TypeSchemaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    refresh_typed_field_schemas(runtime.published_jobs, runtime.type_library.all(), actor=admin.id)
