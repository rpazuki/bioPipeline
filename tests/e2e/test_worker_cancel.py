import threading
import time
from pathlib import Path

from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.models import JobSpec, JobStatus
from bio_pipeline_manager.runner import LocalSubprocessRunner
from bio_pipeline_manager.storage import JobStore
from bio_pipeline_manager.worker import JobWorker


def _install_fake_labutils(tmp_path: Path, body: str) -> dict[str, str]:
    fake = tmp_path / "fake_labutils"
    script_dir = fake / "labUtils" / "scripts"
    script_dir.mkdir(parents=True)
    (fake / "labUtils" / "__init__.py").write_text("", encoding="utf-8")
    (script_dir / "__init__.py").write_text("", encoding="utf-8")
    (script_dir / "run_a_pipeline.py").write_text(body, encoding="utf-8")
    return {"PYTHONPATH": str(fake)}


def test_cancel_kills_running_subprocess(tmp_path: Path):
    env = _install_fake_labutils(
        tmp_path,
        "import sys, time\n"
        "for _ in range(200):\n"
        "    time.sleep(0.1)\n",
    )
    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")
    job = queue.submit(
        JobSpec(
            yaml_path=tmp_path / "pipe.yaml",
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
    env = _install_fake_labutils(
        tmp_path,
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('yaml_file')\n"
        "p.add_argument('pipeline_name')\n"
        "p.add_argument('-o', '--output-dir', required=True)\n"
        "p.add_argument('-i', '--input', action='append', default=[])\n"
        "p.parse_args()\n",
    )
    store = JobStore(tmp_path / "state.sqlite")
    runner = LocalSubprocessRunner(store, extra_env=env)
    queue = JobQueue(store, tmp_path / "logs", runner=runner)
    job = queue.submit(
        JobSpec(
            yaml_path=tmp_path / "pipe.yaml",
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
