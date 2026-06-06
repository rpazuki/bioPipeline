import threading
import time
from pathlib import Path

from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.models import JobSpec, JobStatus
from bio_pipeline_manager.runner import LocalSubprocessRunner
from bio_pipeline_manager.storage import JobStore
from bio_pipeline_manager.worker import JobWorker


def _install_slow_process(tmp_path: Path) -> dict[str, str]:
    """Create an importable package with a process function that sleeps."""
    pkg_root = tmp_path / "slowpkg_root"
    pkg = pkg_root / "slowpkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        "import time\n\n\ndef run(**kwargs):\n    for _ in range(200):\n        time.sleep(0.1)\n",
        encoding="utf-8",
    )
    return {"PYTHONPATH": str(pkg_root)}


def _write_pipeline(yaml_path: Path, *, package: str, method: str) -> None:
    yaml_path.write_text(
        f"""
pipelines:
  - demo:
      Inputs: []
      Processes:
        - step:
            package: {package}
            method: {method}
            parameters: {{}}
      Outputs: []
""",
        encoding="utf-8",
    )


def test_cancel_kills_running_subprocess(tmp_path: Path):
    env = _install_slow_process(tmp_path)
    yaml_path = tmp_path / "pipe.yaml"
    _write_pipeline(yaml_path, package="slowpkg", method="run")

    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")
    job = queue.submit(
        JobSpec(
            yaml_path=yaml_path,
            pipeline_name="demo",
            output_dir=tmp_path / "out",
        )
    )

    runner = LocalSubprocessRunner(store, extra_env=env)
    thread = threading.Thread(target=runner.run, args=(job.id,))
    thread.start()

    # Wait until the runner has claimed the job and recorded the pid.
    for _ in range(50):
        if store.get_job(job.id).pid:
            break
        time.sleep(0.1)
    assert store.get_job(job.id).status == JobStatus.RUNNING

    queue.cancel(job.id)
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert store.get_job(job.id).status == JobStatus.CANCELLED


def test_worker_drains_due_jobs(tmp_path: Path):
    yaml_path = tmp_path / "pipe.yaml"
    # sequence() is a project helper, so no external env is needed.
    yaml_path.write_text(
        """
pipelines:
  - demo:
      Inputs: []
      Processes:
        - step:
            package: pipeline.helpers
            method: sequence
            parameters:
              start: 0
              stop: 3
              step: 1
      Outputs: []
""",
        encoding="utf-8",
    )

    store = JobStore(tmp_path / "state.sqlite")
    runner = LocalSubprocessRunner(store)
    queue = JobQueue(store, tmp_path / "logs", runner=runner)
    job = queue.submit(
        JobSpec(
            yaml_path=yaml_path,
            pipeline_name="demo",
            output_dir=tmp_path / "out",
        )
    )

    worker = JobWorker(queue, interval=0.1)
    worker.start()
    try:
        for _ in range(100):
            if store.get_job(job.id).status == JobStatus.SUCCEEDED:
                break
            time.sleep(0.1)
    finally:
        worker.stop()

    assert store.get_job(job.id).status == JobStatus.SUCCEEDED
