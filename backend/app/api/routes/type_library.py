from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime, require_admin
from app.schemas.pipelines import TypeDefRequest, TypeDefResponse, TypeLibraryResponse
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.type_schema import TypeSchemaError

# The project-level type library is managed on the Environment page (admin-only),
# alongside the Python packages the types are usually extracted from.
router = APIRouter(prefix="/type-library", tags=["type-library"], dependencies=[Depends(require_admin)])


def _response(name: str, type_def: dict[str, Any]) -> TypeDefResponse:
    return TypeDefResponse(
        name=name,
        description=str(type_def.get("description", "") or ""),
        fields=type_def.get("fields") or {},
    )


@router.get("", response_model=TypeLibraryResponse)
async def list_types(runtime: Annotated[PipelineRuntime, Depends(get_runtime)]) -> TypeLibraryResponse:
    library = runtime.type_library.all()
    return TypeLibraryResponse(types=[_response(name, library[name]) for name in sorted(library)])


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
) -> TypeDefResponse:
    try:
        stored = runtime.type_library.upsert(name, body.model_dump())
    except TypeSchemaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _response(name, stored)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_type(
    name: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> None:
    try:
        runtime.type_library.delete(name)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Type '{name}' not found") from exc
    except TypeSchemaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
