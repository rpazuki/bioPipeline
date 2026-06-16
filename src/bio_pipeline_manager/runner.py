from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

from bio_pipeline_manager.models import JobRecord, JobStatus, utc_now
from bio_pipeline_manager.storage import JobStore

logger = logging.getLogger(__name__)

# The src/ directory, so the subprocess can import `bio_pipeline_manager`
# and `pipeline` regardless of how the project is installed.
_SRC_DIR = Path(__file__).resolve().parents[1]


def _kill_process_tree(process: subprocess.Popen) -> None:
    """Kill a subprocess and ALL of its descendants.

    A pipeline Task can spawn children (e.g. cobra's multiprocessing pool), so
    terminating only the direct child leaves grandchildren orphaned and still
    holding resources. On Windows we use ``taskkill /T`` to walk the tree; on
    POSIX we kill the child's process group (the child is started in its own
    session via ``start_new_session`` so the group id equals its pid).
    """
    pid = process.pid
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception:  # noqa: BLE001 - fall back to a plain kill
                process.kill()
    except Exception:  # noqa: BLE001 - last-resort, never raise from cleanup
        try:
            process.kill()
        except Exception:  # noqa: BLE001
            pass


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
        task_timeout: float | None = None,
        log_level: str | None = None,
    ):
        self.store = store
        self.python_executable = str(python_executable or sys.executable)
        self.extra_env = extra_env or {}
        # None / non-positive disables the watchdog (wait is unbounded).
        self.task_timeout = task_timeout if task_timeout and task_timeout > 0 else None
        # Verbosity the task subprocess logs at — propagated from the backend's
        # configured `log_level` so executed jobs match the API's verbosity.
        self.log_level = log_level

    def write_task_file(self, job: JobRecord) -> Path:
        """Materialise the Task as a JSON file next to its log."""
        task = {
            "yaml_path": str(job.spec.yaml_path),
            "pipeline_name": job.spec.pipeline_name,
            "output_dir": str(job.spec.output_dir),
            "input_sources": job.spec.input_sources,
            "input_arg_mapping": job.spec.input_arg_mapping,
            "process_arg_mapping": job.spec.process_arg_mapping,
            "output_path_mapping": job.spec.output_path_mapping,
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
        # Propagate the configured log level so the task subprocess emits at the same
        # verbosity as the backend. Read by bio_pipeline_manager.run_task; the env var
        # name is paired with LOG_LEVEL_ENV there — keep the two in sync.
        if self.log_level:
            env["BIO_PIPELINE_LOG_LEVEL"] = str(self.log_level)
        # Ensure the subprocess can import the project packages from src/.
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{_SRC_DIR}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(_SRC_DIR)
        )

        # On POSIX, start the child in its own session so the watchdog can kill
        # the whole process group (child + any grandchildren it spawns).
        popen_kwargs: dict = {}
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True

        timed_out = False
        with job.log_path.open("w", encoding="utf-8") as log_file:
            log_file.write("$ " + " ".join(command) + "\n\n")
            log_file.flush()
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,  # no inherited console; a stray input() must fail fast, not hang
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                **popen_kwargs,
            )
            self.store.set_pid(job.id, process.pid)
            # A cancel may have raced in after the claim but before the pid was
            # recorded, so it could not signal the process — honor it now.
            if self.store.get_job(job.id).status == JobStatus.CANCELLED:
                _kill_process_tree(process)
            try:
                returncode = process.wait(timeout=self.task_timeout)
            except subprocess.TimeoutExpired:
                # Watchdog fired: one task must never freeze the queue. Kill the
                # whole tree, record it in the task log, and fail the job.
                timed_out = True
                logger.warning(
                    "Task %s exceeded timeout of %ss; killing process tree (pid=%s)",
                    job.id,
                    self.task_timeout,
                    process.pid,
                )
                log_file.write(
                    f"\n[runner] Task exceeded timeout of {self.task_timeout:.0f}s "
                    f"and was terminated.\n"
                )
                log_file.flush()
                _kill_process_tree(process)
                try:
                    returncode = process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    returncode = -1
            finally:
                self.store.set_pid(job.id, None)

        # A concurrent cancel may have killed the process and already set the
        # final status; do not clobber it with FAILED.
        current = self.store.get_job(job.id)
        if current.status == JobStatus.CANCELLED:
            return current

        if timed_out:
            status = JobStatus.FAILED
            error = f"Task exceeded timeout of {self.task_timeout:.0f}s and was terminated"
        else:
            status = JobStatus.SUCCEEDED if returncode == 0 else JobStatus.FAILED
            error = None if returncode == 0 else f"Process exited with {returncode}"
        return self.store.update_status(
            job.id,
            status,
            finished_at=utc_now(),
            exit_code=returncode,
            error=error,
        )
