from pathlib import Path

from bio_pipeline_manager.models import JobSpec, JobStatus
from bio_pipeline_manager.storage import JobStore


def test_create_and_get_job(tmp_path: Path):
    store = JobStore(tmp_path / "state.sqlite")
    spec = JobSpec(
        yaml_path=tmp_path / "pipeline.yaml",
        pipeline_name="demo",
        output_dir=tmp_path / "out",
        input_sources={"raw": "raw.csv"},
    )

    created = store.create_job(spec, tmp_path / "logs" / "job.log")
    fetched = store.get_job(created.id)

    assert fetched.status == JobStatus.QUEUED
    assert fetched.spec.pipeline_name == "demo"
    assert fetched.spec.input_sources == {"raw": "raw.csv"}


def test_list_due_jobs_excludes_future_jobs(tmp_path: Path):
    from datetime import datetime, timedelta, timezone

    store = JobStore(tmp_path / "state.sqlite")
    future = datetime.now(timezone.utc) + timedelta(days=1)
    spec = JobSpec(
        yaml_path=tmp_path / "pipeline.yaml",
        pipeline_name="demo",
        output_dir=tmp_path / "out",
        scheduled_at=future,
    )
    store.create_job(spec, tmp_path / "logs" / "job.log")

    assert store.list_due_jobs() == []

