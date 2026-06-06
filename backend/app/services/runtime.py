from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.packages import InstallStore, PackageManager
from bio_pipeline_manager.storage import JobStore
from bio_pipeline_manager.yaml_store import YamlStore


@dataclass(frozen=True)
class PipelineRuntime:
    home: Path
    yaml_store: YamlStore
    job_store: JobStore
    queue: JobQueue
    packages: PackageManager


def create_runtime(home: str | Path) -> PipelineRuntime:
    root = Path(home)
    job_store = JobStore(root / "state.sqlite")
    yaml_store = YamlStore(root / "yamls")
    return PipelineRuntime(
        home=root,
        yaml_store=yaml_store,
        job_store=job_store,
        queue=JobQueue(job_store, root / "logs", yaml_resolver=yaml_store.resolve_name),
        packages=PackageManager(
            InstallStore(root / "installs.sqlite"),
            job_guard=job_store.has_active_jobs,
        ),
    )
