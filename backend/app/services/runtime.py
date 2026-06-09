from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bio_pipeline_manager.auth_service import AuthService
from bio_pipeline_manager.auth_store import AuthStore
from bio_pipeline_manager.job_definition_store import JobDefinitionStore
from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.packages import InstallStore, PackageManager
from bio_pipeline_manager.published_jobs import PublishedJobStore
from bio_pipeline_manager.run_workspace import RunWorkspaceStore
from bio_pipeline_manager.shared_storage import SharedStorage
from bio_pipeline_manager.storage import JobStore
from bio_pipeline_manager.yaml_store import YamlStore


@dataclass(frozen=True)
class PipelineRuntime:
    home: Path
    yaml_store: YamlStore
    job_store: JobStore
    queue: JobQueue
    packages: PackageManager
    definition_store: JobDefinitionStore
    published_jobs: PublishedJobStore
    run_workspaces: RunWorkspaceStore
    shared_storage: SharedStorage
    auth: AuthService


def create_runtime(
    home: str | Path,
    *,
    auth_session_ttl_hours: float = 24.0,
    shared_roots: list[dict] | None = None,
    upload_max_bytes: int | None = None,
    task_timeout: float | None = None,
) -> PipelineRuntime:
    root = Path(home)
    job_store = JobStore(root / "state.sqlite")
    yaml_store = YamlStore(root / "yamls")
    return PipelineRuntime(
        home=root,
        yaml_store=yaml_store,
        job_store=job_store,
        queue=JobQueue(
            job_store,
            root / "logs",
            yaml_resolver=yaml_store.resolve_name,
            task_timeout=task_timeout,
        ),
        packages=PackageManager(
            InstallStore(root / "installs.sqlite"),
            job_guard=job_store.has_active_jobs,
        ),
        definition_store=JobDefinitionStore(root / "job_defs", root / "job_defs_archive"),
        published_jobs=PublishedJobStore(root / "state.sqlite"),
        run_workspaces=(
            RunWorkspaceStore(root / "runs", max_bytes=upload_max_bytes)
            if upload_max_bytes
            else RunWorkspaceStore(root / "runs")
        ),
        shared_storage=SharedStorage(shared_roots),
        auth=AuthService(AuthStore(root / "auth.sqlite"), session_ttl_hours=auth_session_ttl_hours),
    )
