from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime
from app.schemas.pipelines import (
    JobLogResponse,
    JobResponse,
    JobSubmitRequest,
    PublishedRunRewindRequest,
    RecurringJobCreateRequest,
    RecurringJobResponse,
)
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.models import JobRecord, JobSpec, utc_now
from bio_pipeline_manager.recurring_job import RecurringJobRecord
from bio_pipeline_manager.recurring_schedule import RecurringScheduleError, interval_delta


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
        input_arg_mapping=body.input_arg_mapping,
        process_arg_mapping=body.process_arg_mapping,
        output_path_mapping=body.output_path_mapping,
        backend=body.backend,
        scheduled_at=body.scheduled_at,
    )
    return _job_response(runtime.queue.submit(spec))


# NOTE: these /jobs/schedules routes are declared before /jobs/{job_id} so the
# literal "schedules" segment is never captured as a job id.
@router.post("/schedules", response_model=RecurringJobResponse, status_code=status.HTTP_201_CREATED)
async def create_recurring_job(
    body: RecurringJobCreateRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> RecurringJobResponse:
    """Repeat a plain job submission every interval until its end rule."""
    try:
        # Fail early on a missing/invalid YAML so the schedule can't fire forever
        # against a job that will never run.
        if not runtime.yaml_store.resolve_name(body.job.yaml_name).exists():
            raise RecurringScheduleError(f"Pipeline YAML not found: {body.job.yaml_name}")
        interval_delta(body.every_n, body.unit)
        payload = body.job.model_dump(mode="json", exclude={"scheduled_at"})
        record = runtime.recurring_jobs.create(
            name=body.job.pipeline_name or body.job.yaml_name,
            payload=payload,
            every_n=body.every_n,
            unit=body.unit,
            ends_mode=body.ends_mode,
            ends_count=body.ends_count,
            ends_at=body.ends_at,
            first_run_at=body.start_at or utc_now(),
        )
    except (RecurringScheduleError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _recurring_job_response(record)


@router.get("/schedules", response_model=list[RecurringJobResponse])
async def list_recurring_jobs(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> list[RecurringJobResponse]:
    return [_recurring_job_response(record) for record in runtime.recurring_jobs.list()]


@router.post("/schedules/{schedule_id}/stop", response_model=RecurringJobResponse)
async def stop_recurring_job(
    schedule_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> RecurringJobResponse:
    try:
        return _recurring_job_response(runtime.recurring_jobs.set_active(schedule_id, False))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recurring_job(
    schedule_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> None:
    try:
        runtime.recurring_jobs.delete(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


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
        return _job_response(runtime.queue.cancel(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> None:
    try:
        runtime.queue.delete(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{job_id}/rewind", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def rewind_job(
    job_id: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    body: PublishedRunRewindRequest | None = None,
) -> JobResponse:
    scheduled_at = body.scheduled_at if body else None
    try:
        return _job_response(runtime.queue.rewind(job_id, scheduled_at=scheduled_at))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# Sync handler: FastAPI runs it in a threadpool, so the blocking job
# execution never stalls the async event loop.
@router.post("/run-due", response_model=list[JobResponse])
def run_due_jobs(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    parallel: int = 1,
) -> list[JobResponse]:
    return [_job_response(job) for job in runtime.queue.run_due(parallel=parallel)]


def _recurring_job_response(record: RecurringJobRecord) -> RecurringJobResponse:
    return RecurringJobResponse(
        id=record.id,
        name=record.name,
        every_n=record.every_n,
        unit=record.unit,
        ends_mode=record.ends_mode,
        ends_count=record.ends_count,
        ends_at=record.ends_at,
        next_run_at=record.next_run_at,
        runs_done=record.runs_done,
        active=record.active,
        created_at=record.created_at,
        last_run_at=record.last_run_at,
        payload=record.payload,
    )


def _job_response(job: JobRecord) -> JobResponse:
    return JobResponse(
        id=job.id,
        status=job.status.value,
        yaml_path=str(job.spec.yaml_path),
        pipeline_name=job.spec.pipeline_name,
        output_dir=str(job.spec.output_dir),
        # input_sources are string `src` overrides. Coerce defensively so a
        # record stored with a non-string value (e.g. a legacy bad job) never
        # crashes the read path / blocks the whole job list.
        input_sources={key: str(value) for key, value in (job.spec.input_sources or {}).items()},
        input_arg_mapping=job.spec.input_arg_mapping,
        process_arg_mapping=job.spec.process_arg_mapping,
        output_path_mapping=job.spec.output_path_mapping,
        backend=job.spec.backend,
        log_path=str(job.log_path),
        parent_job_id=job.spec.parent_job_id,
        job_name=job.spec.job_name,
        stage=job.spec.stage,
        matrix_key=job.spec.matrix_key,
        created_at=job.created_at,
        updated_at=job.updated_at,
        scheduled_at=job.spec.scheduled_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        exit_code=job.exit_code,
        error=job.error,
        pid=job.pid,
    )
