from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime, require_admin
from app.schemas.pipelines import (
    InstallRequest,
    MemberSearchRequest,
    MemberSearchResponse,
    ModuleInspectRequest,
    ModuleInspectResponse,
    PackageListResponse,
    PackageOpResultResponse,
    SignatureRequest,
    SignatureResponse,
    UninstallRequest,
)
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.package_introspect import (
    PackageIntrospectError,
    get_signature,
    inspect_module,
    search_members,
)
from bio_pipeline_manager.packages import PackageBusyError, PackageError, result_dict

# Every endpoint here requires an authenticated admin session.
router = APIRouter(prefix="/packages", tags=["packages"], dependencies=[Depends(require_admin)])


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


# --- Introspection: explore installed functions/classes (read-only) ---------- #
# These import the target module (running its top-level code), so they stay behind
# the router's admin guard — the same trade-off type-library extraction makes.
@router.post("/inspect", response_model=ModuleInspectResponse)
async def inspect_module_members(body: ModuleInspectRequest) -> ModuleInspectResponse:
    """List the public functions and classes an installed module exposes."""
    try:
        return ModuleInspectResponse(**inspect_module(body.module))
    except PackageIntrospectError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/search", response_model=MemberSearchResponse)
async def search_package_members(body: MemberSearchRequest) -> MemberSearchResponse:
    """Search installed packages' functions/classes by name (case-insensitive)."""
    try:
        return MemberSearchResponse(**search_members(body.query, module=body.module, limit=body.limit))
    except PackageIntrospectError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/signature", response_model=SignatureResponse)
async def get_member_signature(body: SignatureRequest) -> SignatureResponse:
    """Get the signature, docstring and parameters of a function or class."""
    try:
        return SignatureResponse(**get_signature(body.qualified_name))
    except PackageIntrospectError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
