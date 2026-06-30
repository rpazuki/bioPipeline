from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import get_runtime, require_admin
from app.api.routes import (
    ai_chat,
    auth,
    backup,
    job_definition_store,
    job_definition_templates,
    job_definitions,
    jobs,
    packages,
    published_jobs,
    runtime,
    saved_typed_values,
    storage,
    templates,
    type_library,
    users,
    validation,
)
from app.core.config import settings
from bio_pipeline_manager.published_runs import fire_recurring_schedule
from bio_pipeline_manager.recurring_job import RecurringJobRecord, fire_recurring_job
from bio_pipeline_manager.recurring_schedule import RecurringScheduleRecord, RecurringScheduler
from bio_pipeline_manager.run_reaper import RunReaper
from bio_pipeline_manager.worker import JobWorker


def _fire_recurring_schedule(schedule: RecurringScheduleRecord) -> None:
    rt = get_runtime()
    fire_recurring_schedule(
        published_jobs=rt.published_jobs,
        queue=rt.queue,
        run_workspaces=rt.run_workspaces,
        shared=rt.shared_storage,
        yaml_resolver=rt.yaml_store.resolve_name,
        schedules=rt.recurring_schedules,
        schedule=schedule,
    )


def _fire_recurring_job(record: RecurringJobRecord) -> None:
    rt = get_runtime()
    fire_recurring_job(
        queue=rt.queue,
        yaml_resolver=rt.yaml_store.resolve_name,
        jobs=rt.recurring_jobs,
        record=record,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker: JobWorker | None = None
    reaper: RunReaper | None = None
    scheduler: RecurringScheduler | None = None
    job_scheduler: RecurringScheduler | None = None
    if settings.worker_enabled:
        worker = JobWorker(
            get_runtime().queue,
            interval=settings.worker_interval,
            parallel=settings.worker_parallel,
        )
        worker.start()
    if settings.reaper_enabled:
        rt = get_runtime()
        reaper = RunReaper(
            published_jobs=rt.published_jobs,
            run_workspaces=rt.run_workspaces,
            shared_storage=rt.shared_storage,
            group_status=rt.queue.group_status,
            ttl_hours=settings.artifact_ttl_hours,
            interval=settings.reaper_interval,
            recurring_schedules=rt.recurring_schedules,
        )
        reaper.start()
    if settings.worker_enabled:
        scheduler = RecurringScheduler(
            schedules=get_runtime().recurring_schedules,
            fire=_fire_recurring_schedule,
            interval=settings.worker_interval,
        )
        scheduler.start()
        job_scheduler = RecurringScheduler(
            schedules=get_runtime().recurring_jobs,
            fire=_fire_recurring_job,
            interval=settings.worker_interval,
        )
        job_scheduler.start()
    try:
        yield
    finally:
        if worker:
            worker.stop()
        if reaper:
            reaper.stop()
        if scheduler:
            scheduler.stop()
        if job_scheduler:
            job_scheduler.stop()


app = FastAPI(
    title=settings.app_name,
    description="YAML authoring, validation, queueing, and execution backend for labUtils pipelines.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=settings.docs_url,
    redoc_url=settings.redoc_url,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PREFIX = settings.api_prefix

ADMIN_ONLY = [Depends(require_admin)]

app.include_router(auth.router, prefix=PREFIX)
app.include_router(ai_chat.router, prefix=PREFIX, dependencies=ADMIN_ONLY)
app.include_router(users.router, prefix=PREFIX)
app.include_router(storage.router, prefix=PREFIX, dependencies=ADMIN_ONLY)
app.include_router(validation.router, prefix=PREFIX, dependencies=ADMIN_ONLY)
app.include_router(templates.router, prefix=PREFIX, dependencies=ADMIN_ONLY)
app.include_router(jobs.router, prefix=PREFIX, dependencies=ADMIN_ONLY)
app.include_router(job_definitions.router, prefix=PREFIX, dependencies=ADMIN_ONLY)
app.include_router(job_definition_store.router, prefix=PREFIX, dependencies=ADMIN_ONLY)
app.include_router(job_definition_templates.router, prefix=PREFIX, dependencies=ADMIN_ONLY)
app.include_router(packages.router, prefix=PREFIX, dependencies=ADMIN_ONLY)
app.include_router(backup.router, prefix=PREFIX, dependencies=ADMIN_ONLY)
app.include_router(type_library.router, prefix=PREFIX)
app.include_router(published_jobs.router, prefix=PREFIX)
app.include_router(saved_typed_values.router, prefix=PREFIX)
app.include_router(runtime.router, prefix=PREFIX, dependencies=ADMIN_ONLY)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}
