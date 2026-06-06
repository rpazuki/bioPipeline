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

