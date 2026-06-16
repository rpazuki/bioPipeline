import json
from pathlib import Path

from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.models import JobSpec, JobStatus
from bio_pipeline_manager.runner import LocalSubprocessRunner
from bio_pipeline_manager.storage import JobStore


def test_builds_run_task_command_and_task_file(tmp_path: Path):
    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")
    job = queue.submit(
        JobSpec(
            yaml_path=tmp_path / "pipe.yaml",
            pipeline_name="demo",
            output_dir=tmp_path / "out",
            input_sources={"b": "two.csv", "a": "one.csv"},
            process_arg_mapping={"step": {"threshold": "0.5"}},
        )
    )
    runner = LocalSubprocessRunner(store, python_executable="python")

    task_path = runner.write_task_file(job)
    assert runner.build_command(job, task_path) == [
        "python",
        "-m",
        "bio_pipeline_manager.run_task",
        str(task_path),
    ]

    task = json.loads(task_path.read_text(encoding="utf-8"))
    assert task["yaml_path"] == str(tmp_path / "pipe.yaml")
    assert task["pipeline_name"] == "demo"
    assert task["output_dir"] == str(tmp_path / "out")
    assert task["input_sources"] == {"a": "one.csv", "b": "two.csv"}
    assert task["process_arg_mapping"] == {"step": {"threshold": "0.5"}}


def test_watchdog_kills_task_that_exceeds_timeout(tmp_path: Path):
    import sys

    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")
    job = queue.submit(
        JobSpec(
            yaml_path=tmp_path / "pipe.yaml",
            pipeline_name="demo",
            output_dir=tmp_path / "out",
        )
    )

    class SleepRunner(LocalSubprocessRunner):
        # Replace the real run_task command with a child that would run far
        # longer than the watchdog timeout.
        def build_command(self, job, task_path):
            return [sys.executable, "-c", "import time; time.sleep(30)"]

    runner = SleepRunner(store, task_timeout=0.5)
    result = runner.run(job.id)

    assert result.status == JobStatus.FAILED
    assert "timeout" in (result.error or "").lower()
    # The log records the watchdog action for visibility in the log view.
    assert "exceeded timeout" in job.log_path.read_text(encoding="utf-8").lower()


def test_no_timeout_runs_to_completion(tmp_path: Path):
    import sys

    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")
    job = queue.submit(
        JobSpec(
            yaml_path=tmp_path / "pipe.yaml",
            pipeline_name="demo",
            output_dir=tmp_path / "out",
        )
    )

    class QuickRunner(LocalSubprocessRunner):
        def build_command(self, job, task_path):
            return [sys.executable, "-c", "print('done')"]

    # task_timeout=None (default) must leave wait() unbounded and succeed.
    result = QuickRunner(store).run(job.id)
    assert result.status == JobStatus.SUCCEEDED


def test_log_level_forwarded_from_queue_to_runner(tmp_path: Path):
    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs", log_level="DEBUG")
    assert queue.runner.log_level == "DEBUG"


def test_log_level_propagates_into_subprocess_env(tmp_path: Path):
    import sys

    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")
    job = queue.submit(
        JobSpec(
            yaml_path=tmp_path / "pipe.yaml",
            pipeline_name="demo",
            output_dir=tmp_path / "out",
        )
    )

    class EnvEchoRunner(LocalSubprocessRunner):
        # Echo the injected log-level env var to stdout (captured into the task log).
        def build_command(self, job, task_path):
            return [
                sys.executable,
                "-c",
                "import os; print('LEVEL=' + os.environ.get('BIO_PIPELINE_LOG_LEVEL', 'UNSET'))",
            ]

    result = EnvEchoRunner(store, log_level="DEBUG").run(job.id)
    assert result.status == JobStatus.SUCCEEDED
    assert "LEVEL=DEBUG" in job.log_path.read_text(encoding="utf-8")


def test_no_log_level_leaves_subprocess_env_unset(tmp_path: Path, monkeypatch):
    import sys

    # The runner copies os.environ; ensure a developer's exported var doesn't leak in.
    monkeypatch.delenv("BIO_PIPELINE_LOG_LEVEL", raising=False)
    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")
    job = queue.submit(
        JobSpec(
            yaml_path=tmp_path / "pipe.yaml",
            pipeline_name="demo",
            output_dir=tmp_path / "out",
        )
    )

    class EnvEchoRunner(LocalSubprocessRunner):
        def build_command(self, job, task_path):
            return [
                sys.executable,
                "-c",
                "import os; print('LEVEL=' + os.environ.get('BIO_PIPELINE_LOG_LEVEL', 'UNSET'))",
            ]

    # Default (no log_level) must not inject the var, so the subprocess keeps INFO.
    result = EnvEchoRunner(store).run(job.id)
    assert result.status == JobStatus.SUCCEEDED
    assert "LEVEL=UNSET" in job.log_path.read_text(encoding="utf-8")


def test_rejects_unknown_backend(tmp_path: Path):
    import pytest

    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")
    job = queue.submit(
        JobSpec(
            yaml_path=tmp_path / "pipe.yaml",
            pipeline_name="demo",
            output_dir=tmp_path / "out",
            backend="docker",
        )
    )

    with pytest.raises(NotImplementedError):
        LocalSubprocessRunner(store).run(job.id)

    assert store.get_job(job.id).status == JobStatus.QUEUED

