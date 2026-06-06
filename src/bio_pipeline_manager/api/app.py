from pathlib import Path

from bio_pipeline_manager.job_definition import JobDefinitionError, expand
from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.models import JobSpec, as_utc
from bio_pipeline_manager.storage import JobStore
from bio_pipeline_manager.templates import get_template, list_templates
from bio_pipeline_manager.yaml_validation import validate_labutils_yaml
from bio_pipeline_manager.yaml_store import YamlStore


def create_app(home: str | Path = ".bio_pipeline"):
    from datetime import datetime

    from fastapi import FastAPI, HTTPException
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

    class ValidateYamlDocument(BaseModel):
        content: str
        imports: bool = False

    class SubmitJob(BaseModel):
        yaml_name: str
        pipeline_name: str
        output_dir: str
        input_sources: dict[str, str] = {}
        process_arg_mapping: dict[str, dict[str, str]] = {}
        backend: str = "local"
        scheduled_at: str | None = None

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/yamls")
    def list_yamls():
        return [{"name": path.name, "pipelines": yaml_store.pipeline_names(path.name)} for path in yaml_store.list()]

    @app.post("/yamls")
    def save_yaml(document: YamlDocument):
        try:
            path = yaml_store.save(document.name, document.content, overwrite=document.overwrite)
        except (FileExistsError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"name": path.name, "pipelines": yaml_store.pipeline_names(path.name)}

    @app.post("/yamls/validate")
    def validate_yaml_content(document: ValidateYamlDocument):
        return validate_labutils_yaml(document.content, validate_imports=document.imports).as_dict()

    @app.get("/yamls/{name}")
    def get_yaml(name: str):
        try:
            return {"name": name, "content": yaml_store.load(name), "pipelines": yaml_store.pipeline_names(name)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/yamls/{name}/validate")
    def validate_yaml(name: str, imports: bool = False):
        return yaml_store.validate(name, validate_imports=imports).as_dict()

    @app.get("/templates")
    def templates():
        return [
            {
                "name": template.name,
                "description": template.description,
            }
            for template in list_templates()
        ]

    @app.get("/templates/{name}")
    def template(name: str):
        try:
            pipeline_template = get_template(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "name": pipeline_template.name,
            "description": pipeline_template.description,
            "content": pipeline_template.content,
        }

    @app.post("/jobs")
    def submit_job(payload: SubmitJob):
        spec = JobSpec(
            yaml_path=yaml_store.resolve_name(payload.yaml_name),
            pipeline_name=payload.pipeline_name,
            output_dir=Path(payload.output_dir),
            input_sources=payload.input_sources,
            process_arg_mapping=payload.process_arg_mapping,
            backend=payload.backend,
            scheduled_at=as_utc(datetime.fromisoformat(payload.scheduled_at)) if payload.scheduled_at else None,
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
                "scheduled_at": job.spec.scheduled_at.isoformat() if job.spec.scheduled_at else None,
            }
            for job in job_store.list_jobs()
        ]

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            job = job_store.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "id": job.id,
            "status": job.status,
            "pipeline_name": job.spec.pipeline_name,
            "output_dir": str(job.spec.output_dir),
            "log_path": str(job.log_path),
            "scheduled_at": job.spec.scheduled_at.isoformat() if job.spec.scheduled_at else None,
            "exit_code": job.exit_code,
            "error": job.error,
        }

    @app.get("/jobs/{job_id}/logs")
    def get_logs(job_id: str):
        try:
            job = job_store.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        content = job.log_path.read_text(encoding="utf-8") if job.log_path.exists() else ""
        return {"id": job.id, "log": content}

    @app.post("/jobs/run-due")
    def run_due(parallel: int = 1):
        results = queue.run_due(parallel=parallel)
        return [{"id": job.id, "status": job.status} for job in results]

    @app.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        job = queue.cancel(job_id)
        return {"id": job.id, "status": job.status, "error": job.error}

    class DefinitionRequest(BaseModel):
        content: str
        scheduled_at: str | None = None

    def _task_dict(task):
        return {
            "job_name": task.job_name,
            "stage": task.stage,
            "matrix_key": task.matrix_key,
            "needs": task.needs,
            "pipeline_yaml": task.pipeline_yaml,
            "pipeline_name": task.pipeline_name,
            "output_dir": task.output_dir,
            "input_sources": task.input_sources,
            "process_arg_mapping": task.process_arg_mapping,
            "item_index": task.item_index,
        }

    @app.post("/job-definitions/preview")
    def preview_definition(payload: DefinitionRequest):
        try:
            tasks = expand(payload.content)
        except JobDefinitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "job_name": tasks[0].job_name if tasks else "",
            "task_count": len(tasks),
            "tasks": [_task_dict(t) for t in tasks],
        }

    @app.post("/job-definitions")
    def submit_definition(payload: DefinitionRequest):
        try:
            parent_id, _records = queue.submit_definition(
                payload.content,
                yaml_resolver=yaml_store.resolve_name,
                scheduled_at=as_utc(datetime.fromisoformat(payload.scheduled_at)) if payload.scheduled_at else None,
            )
        except (JobDefinitionError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        summary = queue.group_status(parent_id)
        return summary | {
            "tasks": [{"id": t.id, "stage": t.spec.stage, "status": t.status} for t in summary["tasks"]]
        }

    @app.get("/job-definitions")
    def list_definitions():
        return [
            {k: v for k, v in queue.group_status(parent_id).items() if k != "tasks"}
            for parent_id in job_store.list_parent_ids()
        ]

    @app.get("/job-definitions/{parent_id}")
    def get_definition(parent_id: str):
        if parent_id not in job_store.list_parent_ids():
            raise HTTPException(status_code=404, detail=f"Job group not found: {parent_id}")
        summary = queue.group_status(parent_id)
        return summary | {
            "tasks": [
                {"id": t.id, "stage": t.spec.stage, "status": t.status, "matrix_key": t.spec.matrix_key}
                for t in summary["tasks"]
            ]
        }

    return app
