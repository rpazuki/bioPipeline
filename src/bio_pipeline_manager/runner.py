from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from bio_pipeline_manager.models import JobRecord, JobStatus, utc_now
from bio_pipeline_manager.storage import JobStore

# The src/ directory, so the subprocess can import `bio_pipeline_manager`
# and `pipeline` regardless of how the project is installed.
_SRC_DIR = Path(__file__).resolve().parents[1]


class LocalSubprocessRunner:
    """Run pipeline Tasks in an isolated local subprocess.

    Each Task is built and executed in-process by
    ``python -m bio_pipeline_manager.run_task TASK_JSON`` (the project engine),
    so a Task can carry ``process_arg_mapping``.
    """

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

    def write_task_file(self, job: JobRecord) -> Path:
        """Materialise the Task as a JSON file next to its log."""
        task = {
            "yaml_path": str(job.spec.yaml_path),
            "pipeline_name": job.spec.pipeline_name,
            "output_dir": str(job.spec.output_dir),
            "input_sources": job.spec.input_sources,
            "process_arg_mapping": job.spec.process_arg_mapping,
        }
        task_path = job.log_path.with_suffix(".task.json")
        task_path.parent.mkdir(parents=True, exist_ok=True)
        task_path.write_text(json.dumps(task, indent=2, sort_keys=True), encoding="utf-8")
        return task_path

    def build_command(self, job: JobRecord, task_path: Path) -> list[str]:
        return [
            self.python_executable,
            "-m",
            "bio_pipeline_manager.run_task",
            str(task_path),
        ]

    def run(self, job_id: str) -> JobRecord:
        job = self.store.get_job(job_id)
        if job.spec.backend != "local":
            raise NotImplementedError(f"Unsupported backend: {job.spec.backend}")

        # Atomic claim: only the caller that flips QUEUED -> RUNNING runs it.
        if not self.store.claim_job(job_id):
            return self.store.get_job(job_id)
        job = self.store.get_job(job_id)

        job.log_path.parent.mkdir(parents=True, exist_ok=True)
        job.spec.output_dir.mkdir(parents=True, exist_ok=True)

        task_path = self.write_task_file(job)
        command = self.build_command(job, task_path)
        env = os.environ.copy()
        env.update(self.extra_env)
        # Ensure the subprocess can import the project packages from src/.
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{_SRC_DIR}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(_SRC_DIR)
        )

        with job.log_path.open("w", encoding="utf-8") as log_file:
            log_file.write("$ " + " ".join(command) + "\n\n")
            log_file.flush()
            process = subprocess.Popen(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            self.store.set_pid(job.id, process.pid)
            try:
                returncode = process.wait()
            finally:
                self.store.set_pid(job.id, None)

        # A concurrent cancel may have killed the process and already set the
        # final status; do not clobber it with FAILED.
        current = self.store.get_job(job.id)
        if current.status == JobStatus.CANCELLED:
            return current

        status = JobStatus.SUCCEEDED if returncode == 0 else JobStatus.FAILED
        error = None if returncode == 0 else f"Process exited with {returncode}"
        return self.store.update_status(
            job.id,
            status,
            finished_at=utc_now(),
            exit_code=returncode,
            error=error,
        )
