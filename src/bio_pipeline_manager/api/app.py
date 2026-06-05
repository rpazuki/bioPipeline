from __future__ import annotations

from pathlib import Path

from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.models import JobSpec
from bio_pipeline_manager.storage import JobStore
from bio_pipeline_manager.yaml_store import YamlStore


def create_app(home: str | Path = ".bio_pipeline"):
    from fastapi import FastAPI
    from pydantic import BaseModel

    home = Path(home)
    yaml_store = YamlStore(home / "yamls")
    job_store = JobStore(home / "state.sqlite")
    queue = JobQueue(job_store, home / "logs")
    app = FastAPI(title="Bio Pipeline Manager")

    class YamlDocument(BaseModel):
        name: str
        content: str
        overwrite: bool = False

    class SubmitJob(BaseModel):
        yaml_name: str
        pipeline_name: str
        output_dir: str
        input_sources: dict[str, str] = {}
        backend: str = "local"

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/yamls")
    def list_yamls():
        return [{"name": path.name} for path in yaml_store.list()]

    @app.post("/yamls")
    def save_yaml(document: YamlDocument):
        path = yaml_store.save(document.name, document.content, overwrite=document.overwrite)
        return {"name": path.name, "pipelines": yaml_store.pipeline_names(path.name)}

    @app.get("/yamls/{name}")
    def get_yaml(name: str):
        return {"name": name, "content": yaml_store.load(name), "pipelines": yaml_store.pipeline_names(name)}

    @app.post("/jobs")
    def submit_job(payload: SubmitJob):
        spec = JobSpec(
            yaml_path=yaml_store.resolve_name(payload.yaml_name),
            pipeline_name=payload.pipeline_name,
            output_dir=Path(payload.output_dir),
            input_sources=payload.input_sources,
            backend=payload.backend,
        )
        job = queue.submit(spec)
        return {"id": job.id, "status": job.status, "log_path": str(job.log_path)}

    @app.get("/jobs")
    def list_jobs():
        return [
            {
                "id": job.id,
                "status": job.status,
                "pipeline_name": job.spec.pipeline_name,
                "log_path": str(job.log_path),
            }
            for job in job_store.list_jobs()
        ]

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        job = job_store.get_job(job_id)
        return {
            "id": job.id,
            "status": job.status,
            "pipeline_name": job.spec.pipeline_name,
            "output_dir": str(job.spec.output_dir),
            "log_path": str(job.log_path),
            "exit_code": job.exit_code,
            "error": job.error,
        }

    @app.get("/jobs/{job_id}/logs")
    def get_logs(job_id: str):
        job = job_store.get_job(job_id)
        content = job.log_path.read_text(encoding="utf-8") if job.log_path.exists() else ""
        return {"id": job.id, "log": content}

    @app.post("/jobs/run-due")
    def run_due(parallel: int = 1):
        results = queue.run_due(parallel=parallel)
        return [{"id": job.id, "status": job.status} for job in results]

    return app

