from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import get_runtime
from app.api.routes import (
    job_definition_store,
    job_definition_templates,
    job_definitions,
    jobs,
    packages,
    runtime,
    storage,
    templates,
    validation,
)
from app.core.config import settings
from bio_pipeline_manager.worker import JobWorker


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker: JobWorker | None = None
    if settings.worker_enabled:
        worker = JobWorker(
            get_runtime().queue,
            interval=settings.worker_interval,
            parallel=settings.worker_parallel,
        )
        worker.start()
    try:
        yield
    finally:
        if worker:
            worker.stop()


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

app.include_router(storage.router, prefix=PREFIX)
app.include_router(validation.router, prefix=PREFIX)
app.include_router(templates.router, prefix=PREFIX)
app.include_router(jobs.router, prefix=PREFIX)
app.include_router(job_definitions.router, prefix=PREFIX)
app.include_router(job_definition_store.router, prefix=PREFIX)
app.include_router(job_definition_templates.router, prefix=PREFIX)
app.include_router(packages.router, prefix=PREFIX)
app.include_router(runtime.router, prefix=PREFIX)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}
