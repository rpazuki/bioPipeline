from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from bio_pipeline_manager.models import JobRecord, JobStatus, utc_now
from bio_pipeline_manager.storage import JobStore


class LocalSubprocessRunner:
    """Run labUtils pipelines in an isolated local subprocess."""

    def __init__(
        self,
        store: JobStore,
        *,
        python_executable: str | Path | None = None,
        extra_env: dict[str, str] | None = None,
    ):
        self.store = store
        self.python_executable = str(python_executable or sys.executable)
        self.extra_env = extra_env or {}

    def build_command(self, job: JobRecord) -> list[str]:
        command = [
            self.python_executable,
            "-m",
            "labUtils.scripts.run_a_pipeline",
            str(job.spec.yaml_path),
            job.spec.pipeline_name,
            "-o",
            str(job.spec.output_dir),
        ]
        for name, source in sorted(job.spec.input_sources.items()):
            command.extend(["-i", f"{name}={source}"])
        return command

    def run(self, job_id: str) -> JobRecord:
        job = self.store.get_job(job_id)
        if job.status != JobStatus.QUEUED:
            return job
        if job.spec.backend != "local":
            raise NotImplementedError(f"Unsupported backend: {job.spec.backend}")

        job.log_path.parent.mkdir(parents=True, exist_ok=True)
        job.spec.output_dir.mkdir(parents=True, exist_ok=True)
        self.store.update_status(job.id, JobStatus.RUNNING, started_at=utc_now())

        command = self.build_command(job)
        env = os.environ.copy()
        env.update(self.extra_env)

        with job.log_path.open("w", encoding="utf-8") as log_file:
            log_file.write("$ " + " ".join(command) + "\n\n")
            log_file.flush()
            completed = subprocess.run(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                check=False,
            )

        status = JobStatus.SUCCEEDED if completed.returncode == 0 else JobStatus.FAILED
        error = None if completed.returncode == 0 else f"Process exited with {completed.returncode}"
        return self.store.update_status(
            job.id,
            status,
            finished_at=utc_now(),
            exit_code=completed.returncode,
            error=error,
        )
