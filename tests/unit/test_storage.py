import sqlite3
from pathlib import Path

import pytest

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


def test_create_job_normalizes_naive_schedule_to_utc(tmp_path: Path):
    from datetime import datetime, timezone

    store = JobStore(tmp_path / "state.sqlite")
    spec = JobSpec(
        yaml_path=tmp_path / "pipeline.yaml",
        pipeline_name="demo",
        output_dir=tmp_path / "out",
        scheduled_at=datetime(2026, 1, 1, 12, 0, 0),
    )

    job = store.create_job(spec, tmp_path / "logs" / "job.log")

    assert job.spec.scheduled_at is not None
    assert job.spec.scheduled_at.tzinfo == timezone.utc


def test_cancel_queued_job(tmp_path: Path):
    store = JobStore(tmp_path / "state.sqlite")
    spec = JobSpec(
        yaml_path=tmp_path / "pipeline.yaml",
        pipeline_name="demo",
        output_dir=tmp_path / "out",
    )
    job = store.create_job(spec, tmp_path / "logs" / "job.log")

    cancelled = store.cancel_job(job.id)

    assert cancelled.status == JobStatus.CANCELLED
    assert store.list_due_jobs() == []


def test_round_trips_all_grouping_fields(tmp_path: Path):
    store = JobStore(tmp_path / "state.sqlite")
    spec = JobSpec(
        yaml_path=tmp_path / "pipeline.yaml",
        pipeline_name="demo",
        output_dir=tmp_path / "out",
        input_sources={"raw": "raw.csv"},
        process_arg_mapping={"step": {"k": "v"}},
        parent_job_id="parent-123",
        job_name="my_job",
        stage="preprocess",
        matrix_key={"run_tag": "A", "variant": "x"},
        depends_on=["dep-1", "dep-2"],
    )
    created = store.create_job(spec, tmp_path / "logs" / "job.log")

    fetched = store.get_job(created.id).spec
    assert fetched.process_arg_mapping == {"step": {"k": "v"}}
    assert fetched.parent_job_id == "parent-123"
    assert fetched.job_name == "my_job"
    assert fetched.stage == "preprocess"
    assert fetched.matrix_key == {"run_tag": "A", "variant": "x"}
    assert fetched.depends_on == ["dep-1", "dep-2"]
    assert store.get_job(created.id).updated_at is not None


def test_migrates_legacy_schema(tmp_path: Path):
    """A pre-existing DB without the newer columns is migrated in-place."""
    db_path = tmp_path / "state.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            yaml_path TEXT NOT NULL,
            pipeline_name TEXT NOT NULL,
            output_dir TEXT NOT NULL,
            input_sources TEXT NOT NULL,
            backend TEXT NOT NULL,
            status TEXT NOT NULL,
            log_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            scheduled_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            exit_code INTEGER,
            error TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO jobs (id, yaml_path, pipeline_name, output_dir, input_sources, backend, status, "
        "log_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("legacy-1", "p.yaml", "demo", "out", "{}", "local", "queued", "x.log", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    store = JobStore(db_path)  # triggers migrations
    job = store.get_job("legacy-1")

    assert job.status == JobStatus.QUEUED
    assert job.spec.process_arg_mapping == {}
    assert job.spec.depends_on == []
    assert job.spec.matrix_key == {}
    assert job.updated_at is not None
    assert job.pid is None


def test_parent_queries_and_delete(tmp_path: Path):
    store = JobStore(tmp_path / "state.sqlite")

    def _spec(parent: str | None) -> JobSpec:
        return JobSpec(
            yaml_path=tmp_path / "p.yaml",
            pipeline_name="demo",
            output_dir=tmp_path / "out",
            parent_job_id=parent,
        )

    a1 = store.create_job(_spec("group-a"), tmp_path / "logs" / "a1.log")
    store.create_job(_spec("group-a"), tmp_path / "logs" / "a2.log")
    store.create_job(_spec("group-b"), tmp_path / "logs" / "b1.log")
    store.create_job(_spec(None), tmp_path / "logs" / "solo.log")

    assert len(store.list_jobs_by_parent("group-a")) == 2
    assert set(store.list_parent_ids()) == {"group-a", "group-b"}

    log_file = a1.log_path
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("log", encoding="utf-8")
    store.delete_job(a1.id)
    assert not log_file.exists()
    assert len(store.list_jobs_by_parent("group-a")) == 1


def test_delete_refuses_running_job(tmp_path: Path):
    store = JobStore(tmp_path / "state.sqlite")
    spec = JobSpec(yaml_path=tmp_path / "p.yaml", pipeline_name="demo", output_dir=tmp_path / "out")
    job = store.create_job(spec, tmp_path / "logs" / "job.log")
    store.claim_job(job.id)  # QUEUED -> RUNNING

    with pytest.raises(ValueError, match="running"):
        store.delete_job(job.id)
