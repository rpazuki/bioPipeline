from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime, require_package_admin
from app.schemas.pipelines import (
    InstallRequest,
    PackageListResponse,
    PackageOpResultResponse,
    UninstallRequest,
)
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.packages import PackageBusyError, PackageError, result_dict

# Every endpoint here requires the admin token (auth + audit surface).
router = APIRouter(prefix="/packages", tags=["packages"], dependencies=[Depends(require_package_admin)])


@router.get("", response_model=PackageListResponse)
async def list_packages(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> PackageListResponse:
    return PackageListResponse(
        installed=runtime.packages.list_installed(),
        history=runtime.packages.store.history(),
    )


@router.post("/install", response_model=PackageOpResultResponse)
async def install_package(
    body: InstallRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> PackageOpResultResponse:
    try:
        result = runtime.packages.install(body.spec, source_type=body.source_type, actor="api")
    except PackageBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PackageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PackageOpResultResponse(**result_dict(result))


@router.post("/uninstall", response_model=PackageOpResultResponse)
async def uninstall_package(
    body: UninstallRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> PackageOpResultResponse:
    try:
        result = runtime.packages.uninstall(body.name, actor="api")
    except PackageBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PackageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PackageOpResultResponse(**result_dict(result))
