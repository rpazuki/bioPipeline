from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime
from app.schemas.pipelines import JobLogResponse, JobResponse, JobSubmitRequest
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.models import JobRecord, JobSpec


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> list[JobResponse]:
    return [_job_response(job) for job in runtime.job_store.list_jobs()]


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def submit_job(
    body: JobSubmitRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> JobResponse:
    spec = JobSpec(
        yaml_path=runtime.yaml_store.resolve_name(body.yaml_name),
        pipeline_name=body.pipeline_name,
        output_dir=Path(body.output_dir),
        input_sources=body.input_sources,
        backend=body.backend,
        scheduled_at=body.scheduled_at,
    )
    return _job_response(runtime.queue.submit(spec))


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> JobResponse:
    try:
        return _job_response(runtime.job_store.get_job(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{job_id}/logs", response_model=JobLogResponse)
async def get_job_logs(
    job_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> JobLogResponse:
    try:
        job = runtime.job_store.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    content = job.log_path.read_text(encoding="utf-8") if job.log_path.exists() else ""
    return JobLogResponse(id=job.id, log=content)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> JobResponse:
    try:
        return _job_response(runtime.job_store.cancel_job(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/run-due", response_model=list[JobResponse])
async def run_due_jobs(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    parallel: int = 1,
) -> list[JobResponse]:
    return [_job_response(job) for job in runtime.queue.run_due(parallel=parallel)]


def _job_response(job: JobRecord) -> JobResponse:
    return JobResponse(
        id=job.id,
        status=job.status.value,
        yaml_path=str(job.spec.yaml_path),
        pipeline_name=job.spec.pipeline_name,
        output_dir=str(job.spec.output_dir),
        input_sources=job.spec.input_sources,
        backend=job.spec.backend,
        log_path=str(job.log_path),
        created_at=job.created_at,
        scheduled_at=job.spec.scheduled_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        exit_code=job.exit_code,
        error=job.error,
    )
