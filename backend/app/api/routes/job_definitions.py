from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime
from app.api.routes.jobs import _job_response
from app.schemas.pipelines import (
    JobDefinitionPreviewResponse,
    JobDefinitionRequest,
    JobGroupDetail,
    JobGroupSummary,
    MaterializedTaskResponse,
)
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.job_definition import (
    JobDefinitionError,
    definition_warnings,
    expand,
    parse_job_definition,
)


router = APIRouter(prefix="/job-definitions", tags=["job-definitions"])


@router.post("/preview", response_model=JobDefinitionPreviewResponse)
async def preview_job_definition(body: JobDefinitionRequest) -> JobDefinitionPreviewResponse:
    """Expand a Job Definition into its Tasks without queueing anything."""
    try:
        job_def = parse_job_definition(body.content)
        tasks = expand(job_def, lenient=True)
    except JobDefinitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return JobDefinitionPreviewResponse(
        job_name=tasks[0].job_name if tasks else job_def.name,
        task_count=len(tasks),
        warnings=definition_warnings(job_def),
        tasks=[
            MaterializedTaskResponse(
                job_name=task.job_name,
                stage=task.stage,
                matrix_key=task.matrix_key,
                needs=task.needs,
                pipeline_yaml=task.pipeline_yaml,
                pipeline_name=task.pipeline_name,
                output_dir=task.output_dir,
                input_sources=task.input_sources,
                input_arg_mapping=task.input_arg_mapping,
                process_arg_mapping=task.process_arg_mapping,
                output_path_mapping=task.output_path_mapping,
                item_index=task.item_index,
                deferred=task.deferred,
            )
            for task in tasks
        ],
    )


@router.post("", response_model=JobGroupDetail, status_code=status.HTTP_201_CREATED)
async def submit_job_definition(
    body: JobDefinitionRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> JobGroupDetail:
    """Expand and queue a Job Definition as one parent group of Tasks."""
    try:
        parent_id, _records = runtime.queue.submit_definition(
            body.content,
            yaml_resolver=runtime.yaml_store.resolve_name,
            scheduled_at=body.scheduled_at,
        )
    except (JobDefinitionError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _group_detail(runtime, parent_id)


@router.get("", response_model=list[JobGroupSummary])
async def list_job_definitions(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> list[JobGroupSummary]:
    summaries = []
    for parent_id in runtime.job_store.list_parent_ids():
        summary = runtime.queue.group_status(parent_id)
        summaries.append(_group_summary(summary))
    return summaries


@router.get("/{parent_job_id}", response_model=JobGroupDetail)
async def get_job_definition(
    parent_job_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> JobGroupDetail:
    if parent_job_id not in runtime.job_store.list_parent_ids():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job group not found: {parent_job_id}")
    return _group_detail(runtime, parent_job_id)


def _group_summary(summary: dict) -> JobGroupSummary:
    return JobGroupSummary(
        parent_job_id=summary["parent_job_id"],
        job_name=summary["job_name"],
        status=summary["status"],
        total=summary["total"],
        counts=summary["counts"],
    )


def _group_detail(runtime: PipelineRuntime, parent_job_id: str) -> JobGroupDetail:
    summary = runtime.queue.group_status(parent_job_id)
    return JobGroupDetail(
        parent_job_id=summary["parent_job_id"],
        job_name=summary["job_name"],
        status=summary["status"],
        total=summary["total"],
        counts=summary["counts"],
        tasks=[_job_response(task) for task in summary["tasks"]],
    )
