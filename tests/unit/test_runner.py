from pathlib import Path

from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.models import JobSpec, JobStatus
from bio_pipeline_manager.runner import LocalSubprocessRunner
from bio_pipeline_manager.storage import JobStore


def test_builds_labutils_command(tmp_path: Path):
    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")
    job = queue.submit(
        JobSpec(
            yaml_path=tmp_path / "pipe.yaml",
            pipeline_name="demo",
            output_dir=tmp_path / "out",
            input_sources={"b": "two.csv", "a": "one.csv"},
        )
    )
    runner = LocalSubprocessRunner(store, python_executable="python")

    assert runner.build_command(job) == [
        "python",
        "-m",
        "labUtils.scripts.run_a_pipeline",
        str(tmp_path / "pipe.yaml"),
        "demo",
        "-o",
        str(tmp_path / "out"),
        "-i",
        "a=one.csv",
        "-i",
        "b=two.csv",
    ]


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

