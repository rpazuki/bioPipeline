from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.api.deps import get_runtime, require_admin, require_authenticated_user
from app.api.routes.job_definitions import _group_detail
from app.schemas.pipelines import (
    DraftRunResponse,
    PublishedJobAdminResponse,
    PublishedJobInspectRequest,
    PublishedJobInspectResponse,
    PublishedJobPublicDetail,
    PublishedJobPublicSummary,
    PublishedJobRunRequest,
    PublishedJobSaveRequest,
    PublishedJobUpdateRequest,
    PublishedRunDetail,
    PublishedRunRewindRequest,
    PublishedRunSummary,
    RecurringScheduleCreateRequest,
    RecurringScheduleResponse,
    RunUploadResponse,
    SharedBrowseResponse,
    SharedEntryResponse,
    SharedRootInfo,
)
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.auth_models import UserRecord
from bio_pipeline_manager.job_definition import (
    JobDefinitionError,
    expand,
    fanout_warnings,
    parse_job_definition,
)
from bio_pipeline_manager.published_jobs import (
    PublishedJobError,
    PublishedJobRecord,
    PublishedRunRecord,
    inspect_definition,
    public_fields,
    render_definition,
    resolve_io,
    resolve_typed_fields,
)
from bio_pipeline_manager.published_runs import execute_published_run, run_needs_workspace
from bio_pipeline_manager.recurring_schedule import (
    RecurringScheduleError,
    RecurringScheduleRecord,
    interval_delta,
)
from bio_pipeline_manager.models import utc_now
from bio_pipeline_manager.run_workspace import RunWorkspaceError
from bio_pipeline_manager.shared_storage import SharedStorageError
from bio_pipeline_manager.typed_value_store import typed_value_key

router = APIRouter(prefix="/published-jobs", tags=["published-jobs"])

logger = logging.getLogger(__name__)


@router.post("/admin/inspect", response_model=PublishedJobInspectResponse)
async def inspect_published_job_definition(
    body: PublishedJobInspectRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    _admin: Annotated[UserRecord, Depends(require_admin)],
) -> PublishedJobInspectResponse:
    try:
        job_def = parse_job_definition(body.content)
        candidates = inspect_definition(
            body.content,
            yaml_loader=runtime.yaml_store.load,
            type_library=runtime.type_library.all(),
        )
    except (JobDefinitionError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PublishedJobInspectResponse(
        job_name=job_def.name,
        candidates=candidates,
        warnings=fanout_warnings(job_def),
    )


@router.get("/admin", response_model=list[PublishedJobAdminResponse])
async def list_admin_published_jobs(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    _admin: Annotated[UserRecord, Depends(require_admin)],
) -> list[PublishedJobAdminResponse]:
    return [_admin_response(record) for record in runtime.published_jobs.list()]


@router.get("/admin/runs", response_model=list[PublishedRunSummary])
async def list_admin_published_runs(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    _admin: Annotated[UserRecord, Depends(require_admin)],
) -> list[PublishedRunSummary]:
    return [_run_summary(runtime, run) for run in runtime.published_jobs.list_runs()]


@router.get("/admin/shared-roots", response_model=list[SharedRootInfo])
async def list_admin_shared_roots(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    _admin: Annotated[UserRecord, Depends(require_admin)],
) -> list[SharedRootInfo]:
    """All configured shared roots, so an admin can reference their ids on a field."""
    return [SharedRootInfo(id=root.id, label=root.label) for root in runtime.shared_storage.list_roots()]


@router.post("/admin", response_model=PublishedJobAdminResponse, status_code=status.HTTP_201_CREATED)
async def create_admin_published_job(
    body: PublishedJobSaveRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    admin: Annotated[UserRecord, Depends(require_admin)],
) -> PublishedJobAdminResponse:
    try:
        fields = resolve_typed_fields([field.model_dump() for field in body.fields], runtime.type_library.all())
        record = runtime.published_jobs.create(
            name=body.name,
            description=body.description,
            definition_name=body.definition_name,
            definition_content=body.definition_content,
            fields=fields,
            actor=admin.id,
            status=body.status,
        )
    except (PublishedJobError, JobDefinitionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _admin_response(record)


@router.get("/admin/{published_job_id}", response_model=PublishedJobAdminResponse)
async def get_admin_published_job(
    published_job_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    _admin: Annotated[UserRecord, Depends(require_admin)],
) -> PublishedJobAdminResponse:
    return _admin_response(_get_published_job(runtime, published_job_id))


@router.delete("/admin/{published_job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_published_job(
    published_job_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    _admin: Annotated[UserRecord, Depends(require_admin)],
    force: bool = False,
) -> None:
    try:
        runtime.published_jobs.delete(published_job_id, force=force)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PublishedJobError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/admin/{published_job_id}", response_model=PublishedJobAdminResponse)
async def update_admin_published_job(
    published_job_id: str,
    body: PublishedJobUpdateRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    admin: Annotated[UserRecord, Depends(require_admin)],
) -> PublishedJobAdminResponse:
    try:
        fields = (
            resolve_typed_fields([field.model_dump() for field in body.fields], runtime.type_library.all())
            if body.fields is not None
            else None
        )
        record = runtime.published_jobs.update(
            published_job_id,
            name=body.name,
            description=body.description,
            definition_name=body.definition_name,
            definition_content=body.definition_content,
            fields=fields,
            actor=admin.id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (PublishedJobError, JobDefinitionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _admin_response(record)


@router.post("/admin/{published_job_id}/publish", response_model=PublishedJobAdminResponse)
async def publish_admin_published_job(
    published_job_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    admin: Annotated[UserRecord, Depends(require_admin)],
) -> PublishedJobAdminResponse:
    return _set_admin_status(runtime, published_job_id, "published", admin.id)


@router.post("/admin/{published_job_id}/archive", response_model=PublishedJobAdminResponse)
async def archive_admin_published_job(
    published_job_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    admin: Annotated[UserRecord, Depends(require_admin)],
) -> PublishedJobAdminResponse:
    return _set_admin_status(runtime, published_job_id, "archived", admin.id)


@router.post("/admin/{published_job_id}/validate", response_model=dict)
async def validate_admin_published_job(
    published_job_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    _admin: Annotated[UserRecord, Depends(require_admin)],
) -> dict:
    record = _get_published_job(runtime, published_job_id)
    try:
        job_def = parse_job_definition(record.definition_content)
        candidates = inspect_definition(record.definition_content, yaml_loader=runtime.yaml_store.load)
    except (JobDefinitionError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "is_valid": True,
        "candidate_count": len(candidates),
        "field_count": len(record.fields),
        "run_count": runtime.published_jobs.run_count(record.id),
        "warnings": fanout_warnings(job_def),
    }


@router.post("/admin/{published_job_id}/preview", response_model=dict)
async def preview_admin_published_job(
    published_job_id: str,
    body: PublishedJobRunRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    _admin: Annotated[UserRecord, Depends(require_admin)],
) -> dict:
    record = _get_published_job(runtime, published_job_id)
    try:
        content = render_definition(record, body.values)
        tasks = expand(content, lenient=True)
    except (PublishedJobError, JobDefinitionError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"job_name": tasks[0].job_name if tasks else "", "task_count": len(tasks)}


@router.get("/admin/{published_job_id}/runs", response_model=list[PublishedRunSummary])
async def list_admin_published_job_runs(
    published_job_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    _admin: Annotated[UserRecord, Depends(require_admin)],
) -> list[PublishedRunSummary]:
    _get_published_job(runtime, published_job_id)
    return [
        _run_summary(runtime, run)
        for run in runtime.published_jobs.list_runs(published_job_id=published_job_id)
    ]


@router.get("", response_model=list[PublishedJobPublicSummary])
async def list_published_jobs(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    _user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> list[PublishedJobPublicSummary]:
    return [_public_summary(record) for record in runtime.published_jobs.list(status="published")]


@router.get("/catalog/{published_job_id}", response_model=PublishedJobPublicDetail)
async def get_published_job(
    published_job_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    _user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> PublishedJobPublicDetail:
    record = _get_published_job(runtime, published_job_id)
    if record.status != "published":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published job not found")
    return _public_detail(record)


@router.get("/catalog/{published_job_id}/shared-roots", response_model=list[SharedRootInfo])
async def list_published_job_shared_roots(
    published_job_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    _user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> list[SharedRootInfo]:
    """Roots an admin exposed via this job's shared-input fields (labels only, no server paths)."""
    record = _get_published_job(runtime, published_job_id)
    if record.status != "published":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published job not found")
    referenced = _job_shared_root_ids(record)
    return [
        SharedRootInfo(id=root.id, label=root.label)
        for root in runtime.shared_storage.list_roots()
        if root.id in referenced
    ]


@router.get("/catalog/{published_job_id}/browse", response_model=SharedBrowseResponse)
async def browse_published_job_shared_root(
    published_job_id: str,
    field: str,
    root: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    _user: Annotated[UserRecord, Depends(require_authenticated_user)],
    subpath: str = "",
) -> SharedBrowseResponse:
    """List entries within an allowlisted shared root for a job's shared-input field.

    Only roots the field declares are browsable, and every sub-path is
    containment-checked — the server filesystem is never exposed.
    """
    record = _get_published_job(runtime, published_job_id)
    if record.status != "published":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published job not found")
    try:
        field_def = _shared_field(record, field)
        if root not in (field_def.get("shared_roots") or []):
            raise PublishedJobError(f"Shared root '{root}' is not allowed for this field")
        entries = runtime.shared_storage.browse(root, subpath)
    except (PublishedJobError, SharedStorageError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SharedBrowseResponse(
        root_id=root,
        subpath=subpath,
        entries=[SharedEntryResponse(name=entry.name, path=entry.path, kind=entry.kind) for entry in entries],
    )


@router.post(
    "/catalog/{published_job_id}/runs/draft",
    response_model=DraftRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_published_job_draft_run(
    published_job_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> DraftRunResponse:
    """Reserve a per-run workspace the researcher uploads inputs into before executing."""
    record = _get_published_job(runtime, published_job_id)
    if record.status != "published":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published job not found")
    manifest = runtime.run_workspaces.create(owner_user_id=user.id, published_job_id=record.id)
    return DraftRunResponse(workspace_id=manifest.workspace_id)


@router.post(
    "/catalog/{published_job_id}/runs/{workspace_id}/uploads/{field_id}",
    response_model=RunUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_published_job_run_input(
    published_job_id: str,
    workspace_id: str,
    field_id: str,
    filename: str,
    request: Request,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
    offset: int = 0,
    relpath: str = "",
) -> RunUploadResponse:
    """Stream one uploaded file (or folder member) into the run workspace.

    The body is the raw file bytes (no multipart). ``offset`` enables
    chunked/resumable uploads (each chunk is appended at its offset); ``relpath``
    preserves a file's position within an uploaded folder. The per-run quota is
    enforced while streaming, so an over-large upload is never fully buffered.
    """
    record = _get_published_job(runtime, published_job_id)
    if record.status != "published":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published job not found")
    workspaces = runtime.run_workspaces
    try:
        runtime.run_workspaces.require_owner(workspace_id, user.id)
        _require_upload_field(record, field_id)
        dest, handle = workspaces.prepare_input(workspace_id, field_id, filename, relpath=relpath)
        existing = dest.stat().st_size if dest.exists() else 0
        # Bytes already counted for this file should not be double-charged: an
        # append keeps them, a fresh (offset 0) upload replaces them.
        base = workspaces.total_size(workspace_id) - (existing if offset == 0 else 0)
        written = 0
        mode = "r+b" if offset and dest.exists() else "wb"
        with dest.open(mode) as out:
            if offset:
                out.seek(offset)
            async for chunk in request.stream():
                written += len(chunk)
                if base + written > workspaces.max_bytes:
                    out.close()
                    if offset == 0:
                        dest.unlink(missing_ok=True)
                    raise PublishedJobError("Upload exceeds the per-run size limit")
                out.write(chunk)
    except (RunWorkspaceError, PublishedJobError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return RunUploadResponse(field_id=field_id, handle=handle, filename=dest.name, size=dest.stat().st_size)


@router.post("/catalog/{published_job_id}/runs", response_model=PublishedRunDetail, status_code=status.HTTP_201_CREATED)
async def submit_published_job_run(
    published_job_id: str,
    body: PublishedJobRunRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> PublishedRunDetail:
    record = _get_published_job(runtime, published_job_id)
    if record.status != "published":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published job not found")
    file_bindings = {field_id: binding.model_dump() for field_id, binding in body.file_bindings.items()}
    try:
        if body.workspace_id:
            runtime.run_workspaces.require_owner(body.workspace_id, user.id)
        run = execute_published_run(
            published_jobs=runtime.published_jobs,
            queue=runtime.queue,
            run_workspaces=runtime.run_workspaces,
            shared=runtime.shared_storage,
            yaml_resolver=runtime.yaml_store.resolve_name,
            record=record,
            values=body.values,
            file_bindings=file_bindings,
            workspace_id=body.workspace_id,
            scheduled_at=body.scheduled_at,
            user_id=user.id,
        )
    except (RunWorkspaceError, PublishedJobError, JobDefinitionError, ValueError) as exc:
        # Surface the reason in the server log — the access log only shows "400", so
        # without this the cause (missing input, invalid typed value, …) is invisible.
        logger.warning("Published run rejected for job %s: %s", published_job_id, exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    # Auto-save each typed field's value the FIRST time it is run, so the next run of
    # any job using the same type pre-fills it. An already-saved value is left
    # untouched here — only the explicit Save button may overwrite it. Best-effort: a
    # save hiccup must not fail an already-submitted run.
    _autosave_new_typed_values(runtime, record, body.values, user.id)
    return _run_detail(runtime, run)


def _autosave_new_typed_values(
    runtime: PipelineRuntime,
    record: PublishedJobRecord,
    values: dict,
    user_id: str,
) -> None:
    for field_def in record.fields:
        key = typed_value_key(field_def)
        if key is None:
            continue
        type_key, container = key
        value = values.get(field_def["id"])
        if not value:  # skip empty {} / [] — nothing worth remembering yet
            continue
        try:
            # Only create a saved value that does not exist yet; never overwrite an
            # existing one on execute (the Save button is the only update path).
            if runtime.typed_values.get_by_key(user_id, type_key, container) is not None:
                continue
            runtime.typed_values.upsert(
                user_id=user_id,
                type_key=type_key,
                container=container,
                label=type_key,
                type_schema=field_def.get("type_schema") or {},
                value=value,
            )
        except Exception:  # noqa: BLE001 - saving a convenience value is never fatal
            pass


@router.get("/my-runs", response_model=list[PublishedRunSummary])
async def list_my_published_runs(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> list[PublishedRunSummary]:
    return [_run_summary(runtime, run) for run in runtime.published_jobs.list_runs(user_id=user.id)]


@router.get("/my-runs/{run_id}", response_model=PublishedRunDetail)
async def get_my_published_run(
    run_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> PublishedRunDetail:
    run = _get_owned_run(runtime, run_id, user.id)
    return _run_detail(runtime, run)


@router.get("/my-runs/{run_id}/artifact")
async def download_my_published_run_artifact(
    run_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> FileResponse:
    """Download a finished run's packaged outputs (the retained results archive)."""
    run = _get_owned_run(runtime, run_id, user.id)
    if not run.workspace_id or not runtime.run_workspaces.has_artifact(run.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No results are available for this run")
    return FileResponse(
        runtime.run_workspaces.artifact_path(run.workspace_id),
        media_type="application/zip",
        filename=f"{run.id}-results.zip",
    )


@router.delete("/my-runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_published_run(
    run_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> None:
    """Remove one of the researcher's runs: cancel active tasks, drop the task
    records and the run's workspace, then delete the run link."""
    run = _get_owned_run(runtime, run_id, user.id)
    for task in runtime.job_store.list_jobs_by_parent(run.parent_job_id):
        if task.status.value in {"queued", "running"}:
            try:
                runtime.queue.cancel(task.id)
            except ValueError:
                pass
        try:
            runtime.queue.delete(task.id)
        except Exception:  # noqa: BLE001 - best-effort cleanup of task records
            pass
    if run.workspace_id:
        try:
            runtime.run_workspaces.delete(run.workspace_id)
        except RunWorkspaceError:
            pass
    runtime.published_jobs.delete_run(run_id)


@router.post("/my-runs/{run_id}/cancel", response_model=PublishedRunDetail)
async def cancel_my_published_run(
    run_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> PublishedRunDetail:
    run = _get_owned_run(runtime, run_id, user.id)
    for task in runtime.job_store.list_jobs_by_parent(run.parent_job_id):
        if task.status.value in {"queued", "running"}:
            try:
                runtime.queue.cancel(task.id)
            except ValueError:
                pass
    return _run_detail(runtime, run)


@router.post("/my-runs/{run_id}/rewind", response_model=PublishedRunDetail, status_code=status.HTTP_201_CREATED)
async def rewind_my_published_run(
    run_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
    body: PublishedRunRewindRequest | None = None,
) -> PublishedRunDetail:
    """Re-run a previous run — immediately, or (schedule-again) at ``scheduled_at``.

    A run that used uploaded files is replayed by cloning its retained inputs into
    a fresh workspace; a file-less run replays its frozen rendered definition.
    """
    run = _get_owned_run(runtime, run_id, user.id)
    scheduled_at = body.scheduled_at if body else None
    try:
        if run.workspace_id:
            if not runtime.run_workspaces.exists(run.workspace_id):
                raise PublishedJobError("This run's inputs are no longer available to replay.")
            record = _get_published_job(runtime, run.published_job_id)
            clone = runtime.run_workspaces.clone_inputs(
                run.workspace_id, owner_user_id=user.id, published_job_id=record.id
            )
            new_run = execute_published_run(
                published_jobs=runtime.published_jobs,
                queue=runtime.queue,
                run_workspaces=runtime.run_workspaces,
                shared=runtime.shared_storage,
                yaml_resolver=runtime.yaml_store.resolve_name,
                record=record,
                values=run.values,
                file_bindings=run.file_bindings,
                workspace_id=clone.workspace_id,
                scheduled_at=scheduled_at,
                user_id=user.id,
            )
        else:
            parent_id, _records = runtime.queue.submit_definition(
                run.rendered_definition,
                yaml_resolver=runtime.yaml_store.resolve_name,
                scheduled_at=scheduled_at,
            )
            new_run = runtime.published_jobs.create_run(
                published_job_id=run.published_job_id,
                published_version=run.published_version,
                user_id=user.id,
                values=run.values,
                rendered_definition=run.rendered_definition,
                parent_job_id=parent_id,
            )
    except (RunWorkspaceError, PublishedJobError, JobDefinitionError, ValueError) as exc:
        logger.warning("Rewind rejected for run %s: %s", run_id, exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _run_detail(runtime, new_run)


@router.post(
    "/catalog/{published_job_id}/schedules",
    response_model=RecurringScheduleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_recurring_schedule(
    published_job_id: str,
    body: RecurringScheduleCreateRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> RecurringScheduleResponse:
    """Set up a published job to run again on a fixed interval until its end rule.

    The provided workspace (with any uploaded inputs) becomes the schedule's input
    template; the values/bindings are dry-run validated against a throwaway clone so
    a schedule that could never run is rejected up front rather than failing silently.
    """
    record = _get_published_job(runtime, published_job_id)
    if record.status != "published":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published job not found")
    file_bindings = {field_id: binding.model_dump() for field_id, binding in body.file_bindings.items()}
    template_workspace_id = body.workspace_id or ""
    try:
        if template_workspace_id:
            runtime.run_workspaces.require_owner(template_workspace_id, user.id)
        interval_delta(body.every_n, body.unit)  # validate the period early
        _validate_schedule_runnable(runtime, record, body.values, file_bindings, template_workspace_id, user.id)
        schedule = runtime.recurring_schedules.create(
            user_id=user.id,
            published_job_id=record.id,
            published_version=record.version,
            values=body.values,
            file_bindings=file_bindings,
            template_workspace_id=template_workspace_id,
            every_n=body.every_n,
            unit=body.unit,
            ends_mode=body.ends_mode,
            ends_count=body.ends_count,
            ends_at=body.ends_at,
            first_run_at=body.start_at or utc_now(),
        )
    except (RunWorkspaceError, PublishedJobError, JobDefinitionError, RecurringScheduleError, ValueError) as exc:
        logger.warning("Recurring schedule rejected for job %s: %s", published_job_id, exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _schedule_response(runtime, schedule)


@router.get("/my-schedules", response_model=list[RecurringScheduleResponse])
async def list_my_recurring_schedules(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> list[RecurringScheduleResponse]:
    return [_schedule_response(runtime, s) for s in runtime.recurring_schedules.list(user_id=user.id)]


@router.post("/my-schedules/{schedule_id}/stop", response_model=RecurringScheduleResponse)
async def stop_my_recurring_schedule(
    schedule_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> RecurringScheduleResponse:
    _get_owned_schedule(runtime, schedule_id, user.id)
    return _schedule_response(runtime, runtime.recurring_schedules.set_active(schedule_id, False))


@router.delete("/my-schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_recurring_schedule(
    schedule_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    user: Annotated[UserRecord, Depends(require_authenticated_user)],
) -> None:
    schedule = _get_owned_schedule(runtime, schedule_id, user.id)
    if schedule.template_workspace_id:
        try:
            runtime.run_workspaces.delete(schedule.template_workspace_id)
        except RunWorkspaceError:
            pass
    runtime.recurring_schedules.delete(schedule_id)


def _get_published_job(runtime: PipelineRuntime, published_job_id: str) -> PublishedJobRecord:
    try:
        return runtime.published_jobs.get(published_job_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _validate_schedule_runnable(
    runtime: PipelineRuntime,
    record: PublishedJobRecord,
    values: dict,
    file_bindings: dict,
    template_workspace_id: str,
    user_id: str,
) -> None:
    """Dry-run a schedule against a throwaway workspace so a never-runnable one is
    rejected at creation. Mirrors exactly what the scheduler will do at fire time."""
    probe = ""
    if template_workspace_id and runtime.run_workspaces.exists(template_workspace_id):
        probe = runtime.run_workspaces.clone_inputs(
            template_workspace_id, owner_user_id=user_id, published_job_id=record.id
        ).workspace_id
    elif run_needs_workspace(record):
        probe = runtime.run_workspaces.create(owner_user_id=user_id, published_job_id=record.id).workspace_id
    try:
        resolved = resolve_io(
            record,
            values,
            file_bindings=file_bindings,
            workspaces=runtime.run_workspaces,
            workspace_id=probe or None,
            shared=runtime.shared_storage,
        )
        render_definition(record, resolved)
    finally:
        if probe:
            try:
                runtime.run_workspaces.delete(probe)
            except RunWorkspaceError:
                pass


def _get_owned_schedule(runtime: PipelineRuntime, schedule_id: str, user_id: str) -> RecurringScheduleRecord:
    try:
        schedule = runtime.recurring_schedules.get(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if schedule.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recurring schedule not found")
    return schedule


def _schedule_response(runtime: PipelineRuntime, schedule: RecurringScheduleRecord) -> RecurringScheduleResponse:
    try:
        name = runtime.published_jobs.get(schedule.published_job_id).name
    except KeyError:
        name = schedule.published_job_id
    return RecurringScheduleResponse(
        id=schedule.id,
        published_job_id=schedule.published_job_id,
        published_job_name=name,
        published_version=schedule.published_version,
        every_n=schedule.every_n,
        unit=schedule.unit,
        ends_mode=schedule.ends_mode,
        ends_count=schedule.ends_count,
        ends_at=schedule.ends_at,
        next_run_at=schedule.next_run_at,
        runs_done=schedule.runs_done,
        active=schedule.active,
        created_at=schedule.created_at,
        last_run_at=schedule.last_run_at,
        values=schedule.values,
    )


def _require_upload_field(record: PublishedJobRecord, field_id: str) -> dict:
    for field in record.fields:
        if field.get("id") == field_id:
            if field.get("io_role") != "input":
                raise PublishedJobError(f"Field '{field_id}' is not a researcher input")
            if "upload" not in (field.get("sources") or []):
                raise PublishedJobError(f"Field '{field_id}' does not accept uploads")
            return field
    raise PublishedJobError(f"Unknown field: {field_id}")


def _shared_field(record: PublishedJobRecord, field_id: str) -> dict:
    for field in record.fields:
        if field.get("id") == field_id:
            if field.get("io_role") != "input" or "shared" not in (field.get("sources") or []):
                raise PublishedJobError(f"Field '{field_id}' does not browse shared storage")
            return field
    raise PublishedJobError(f"Unknown field: {field_id}")


def _job_shared_root_ids(record: PublishedJobRecord) -> set[str]:
    ids: set[str] = set()
    for field in record.fields:
        if field.get("io_role") == "input" and "shared" in (field.get("sources") or []):
            ids.update(field.get("shared_roots") or [])
    return ids


def _get_owned_run(runtime: PipelineRuntime, run_id: str, user_id: str) -> PublishedRunRecord:
    try:
        run = runtime.published_jobs.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if run.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published run not found")
    return run


def _set_admin_status(
    runtime: PipelineRuntime,
    published_job_id: str,
    new_status: str,
    actor: str,
) -> PublishedJobAdminResponse:
    try:
        return _admin_response(runtime.published_jobs.set_status(published_job_id, new_status, actor=actor))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PublishedJobError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _admin_response(record: PublishedJobRecord) -> PublishedJobAdminResponse:
    return PublishedJobAdminResponse(
        id=record.id,
        name=record.name,
        description=record.description,
        status=record.status,
        version=record.version,
        definition_name=record.definition_name,
        definition_content=record.definition_content,
        fields=record.fields,
        created_at=record.created_at,
        updated_at=record.updated_at,
        published_at=record.published_at,
        created_by=record.created_by,
        updated_by=record.updated_by,
    )


def _public_summary(record: PublishedJobRecord) -> PublishedJobPublicSummary:
    return PublishedJobPublicSummary(
        id=record.id,
        name=record.name,
        description=record.description,
        version=record.version,
    )


def _public_detail(record: PublishedJobRecord) -> PublishedJobPublicDetail:
    return PublishedJobPublicDetail(
        id=record.id,
        name=record.name,
        description=record.description,
        version=record.version,
        fields=public_fields(record.fields),
    )


def _run_summary(runtime: PipelineRuntime, run: PublishedRunRecord) -> PublishedRunSummary:
    try:
        published = runtime.published_jobs.get(run.published_job_id)
        published_name = published.name
    except KeyError:
        published_name = run.published_job_id
    try:
        user = runtime.auth.get_user(run.user_id)
        username = user.username
        user_display_name = user.display_name
    except KeyError:
        username = run.user_id
        user_display_name = ""
    summary = runtime.queue.group_status(run.parent_job_id)
    artifact_available = bool(run.workspace_id) and runtime.run_workspaces.has_artifact(run.workspace_id)
    return PublishedRunSummary(
        id=run.id,
        published_job_id=run.published_job_id,
        published_version=run.published_version,
        published_job_name=published_name,
        user_id=run.user_id,
        username=username,
        user_display_name=user_display_name,
        parent_job_id=run.parent_job_id,
        status=summary["status"],
        total=summary["total"],
        counts=summary["counts"],
        values=run.values,
        workspace_id=run.workspace_id,
        artifact_available=artifact_available,
        created_at=run.created_at,
    )


def _run_detail(runtime: PipelineRuntime, run: PublishedRunRecord) -> PublishedRunDetail:
    group = _group_detail(runtime, run.parent_job_id)
    logs = {
        task.id: task.log_path.read_text(encoding="utf-8") if task.log_path.exists() else ""
        for task in runtime.job_store.list_jobs_by_parent(run.parent_job_id)
    }
    return PublishedRunDetail(
        **_run_summary(runtime, run).model_dump(),
        group=group,
        logs=logs,
    )
