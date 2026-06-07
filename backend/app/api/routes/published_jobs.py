from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime, require_admin, require_authenticated_user
from app.api.routes.job_definitions import _group_detail
from app.schemas.pipelines import (
    PublishedJobAdminResponse,
    PublishedJobInspectRequest,
    PublishedJobInspectResponse,
    PublishedJobPublicDetail,
    PublishedJobPublicSummary,
    PublishedJobRunRequest,
    PublishedJobSaveRequest,
    PublishedJobUpdateRequest,
    PublishedRunDetail,
    PublishedRunSummary,
)
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.auth_models import UserRecord
from bio_pipeline_manager.job_definition import JobDefinitionError, expand, parse_job_definition
from bio_pipeline_manager.published_jobs import (
    PublishedJobError,
    PublishedJobRecord,
    PublishedRunRecord,
    inspect_definition,
    public_fields,
    render_definition,
)

router = APIRouter(prefix="/published-jobs", tags=["published-jobs"])


@router.post("/admin/inspect", response_model=PublishedJobInspectResponse)
async def inspect_published_job_definition(
    body: PublishedJobInspectRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    _admin: Annotated[UserRecord, Depends(require_admin)],
) -> PublishedJobInspectResponse:
    try:
        job_def = parse_job_definition(body.content)
        candidates = inspect_definition(body.content, yaml_loader=runtime.yaml_store.load)
    except (JobDefinitionError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PublishedJobInspectResponse(job_name=job_def.name, candidates=candidates)


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


@router.post("/admin", response_model=PublishedJobAdminResponse, status_code=status.HTTP_201_CREATED)
async def create_admin_published_job(
    body: PublishedJobSaveRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    admin: Annotated[UserRecord, Depends(require_admin)],
) -> PublishedJobAdminResponse:
    try:
        record = runtime.published_jobs.create(
            name=body.name,
            description=body.description,
            definition_name=body.definition_name,
            definition_content=body.definition_content,
            fields=[field.model_dump() for field in body.fields],
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
        record = runtime.published_jobs.update(
            published_job_id,
            name=body.name,
            description=body.description,
            definition_name=body.definition_name,
            definition_content=body.definition_content,
            fields=[field.model_dump() for field in body.fields] if body.fields is not None else None,
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
        parse_job_definition(record.definition_content)
        candidates = inspect_definition(record.definition_content, yaml_loader=runtime.yaml_store.load)
    except (JobDefinitionError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "is_valid": True,
        "candidate_count": len(candidates),
        "field_count": len(record.fields),
        "run_count": runtime.published_jobs.run_count(record.id),
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
    try:
        rendered = render_definition(record, body.values)
        parent_id, _records = runtime.queue.submit_definition(
            rendered,
            yaml_resolver=runtime.yaml_store.resolve_name,
            scheduled_at=body.scheduled_at,
        )
        run = runtime.published_jobs.create_run(
            published_job_id=record.id,
            published_version=record.version,
            user_id=user.id,
            values=body.values,
            rendered_definition=rendered,
            parent_job_id=parent_id,
        )
    except (PublishedJobError, JobDefinitionError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _run_detail(runtime, run)


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
) -> PublishedRunDetail:
    run = _get_owned_run(runtime, run_id, user.id)
    try:
        parent_id, _records = runtime.queue.submit_definition(
            run.rendered_definition,
            yaml_resolver=runtime.yaml_store.resolve_name,
        )
        new_run = runtime.published_jobs.create_run(
            published_job_id=run.published_job_id,
            published_version=run.published_version,
            user_id=user.id,
            values=run.values,
            rendered_definition=run.rendered_definition,
            parent_job_id=parent_id,
        )
    except (JobDefinitionError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _run_detail(runtime, new_run)


def _get_published_job(runtime: PipelineRuntime, published_job_id: str) -> PublishedJobRecord:
    try:
        return runtime.published_jobs.get(published_job_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


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
