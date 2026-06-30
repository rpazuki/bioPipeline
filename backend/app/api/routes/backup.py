from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_runtime, require_admin
from app.schemas.pipelines import BackupImportReportResponse
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.auth_models import UserRecord
from bio_pipeline_manager.backup import BackupError, build_backup, import_backup

router = APIRouter(prefix="/backup", tags=["backup"])


@router.get("/export")
async def export_backup(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    admin: Annotated[UserRecord, Depends(require_admin)],
) -> StreamingResponse:
    """Download a single zip bundling pipelines, job definitions, published jobs, the
    type library, and a requirements file of the extra packages installed via the app."""
    data = build_backup(
        yaml_store=runtime.yaml_store,
        definition_store=runtime.definition_store,
        published_jobs=runtime.published_jobs,
        packages=runtime.packages,
        type_library=runtime.type_library,
        created_by=admin.username,
    )
    filename = f"bio-pipeline-backup-{date.today().isoformat()}.zip"
    return StreamingResponse(
        iter([data]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=BackupImportReportResponse)
async def import_backup_route(
    request: Request,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    admin: Annotated[UserRecord, Depends(require_admin)],
    overwrite: bool = False,
    install_packages: bool = True,
) -> BackupImportReportResponse:
    """Apply an uploaded backup zip (raw body). ``overwrite`` off => existing items are
    skipped; on => replaced. ``install_packages`` feeds the bundled requirements.txt
    through the package-install mechanism so imported pipelines/jobs are runnable."""
    body = await request.body()
    if not body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No backup file was uploaded")
    try:
        report = import_backup(
            body,
            yaml_store=runtime.yaml_store,
            definition_store=runtime.definition_store,
            published_jobs=runtime.published_jobs,
            packages=runtime.packages,
            type_library=runtime.type_library,
            overwrite=overwrite,
            install_packages=install_packages,
            actor=admin.username,
        )
    except BackupError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BackupImportReportResponse(**report.as_dict())
