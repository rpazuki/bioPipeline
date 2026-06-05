from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable

from bio_pipeline_manager.models import JobRecord, JobSpec, JobStatus, utc_now


class JobStore:
    """SQLite-backed job state store."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def init(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
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

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_job(self, spec: JobSpec, log_path: str | Path) -> JobRecord:
        job_id = uuid.uuid4().hex
        created_at = utc_now()
        record = JobRecord(
            id=job_id,
            spec=spec,
            status=JobStatus.QUEUED,
            log_path=Path(log_path),
            created_at=created_at,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, yaml_path, pipeline_name, output_dir, input_sources, backend,
                    status, log_path, created_at, scheduled_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    str(spec.yaml_path),
                    spec.pipeline_name,
                    str(spec.output_dir),
                    json.dumps(spec.input_sources, sort_keys=True),
                    spec.backend,
                    record.status.value,
                    str(record.log_path),
                    record.created_at.isoformat(),
                    spec.scheduled_at.isoformat() if spec.scheduled_at else None,
                ),
            )
        return record

    def get_job(self, job_id: str) -> JobRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Job not found: {job_id}")
        return self._row_to_record(row)

    def list_jobs(self) -> list[JobRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_due_jobs(self, limit: int | None = None) -> list[JobRecord]:
        now = utc_now().isoformat()
        query = """
            SELECT * FROM jobs
            WHERE status = ?
              AND (scheduled_at IS NULL OR scheduled_at <= ?)
            ORDER BY created_at ASC
        """
        params: Iterable[object]
        if limit is None:
            params = (JobStatus.QUEUED.value, now)
        else:
            query += " LIMIT ?"
            params = (JobStatus.QUEUED.value, now, limit)
        with self.connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_record(row) for row in rows]

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        exit_code: int | None = None,
        error: str | None = None,
    ) -> JobRecord:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    started_at = COALESCE(?, started_at),
                    finished_at = COALESCE(?, finished_at),
                    exit_code = COALESCE(?, exit_code),
                    error = COALESCE(?, error)
                WHERE id = ?
                """,
                (
                    status.value,
                    started_at.isoformat() if started_at else None,
                    finished_at.isoformat() if finished_at else None,
                    exit_code,
                    error,
                    job_id,
                ),
            )
        return self.get_job(job_id)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> JobRecord:
        scheduled_at = _parse_dt(row["scheduled_at"])
        spec = JobSpec(
            yaml_path=Path(row["yaml_path"]),
            pipeline_name=row["pipeline_name"],
            output_dir=Path(row["output_dir"]),
            input_sources=json.loads(row["input_sources"]),
            backend=row["backend"],
            scheduled_at=scheduled_at,
        )
        return JobRecord(
            id=row["id"],
            spec=spec,
            status=JobStatus(row["status"]),
            log_path=Path(row["log_path"]),
            created_at=_parse_dt(row["created_at"]),
            started_at=_parse_dt(row["started_at"]),
            finished_at=_parse_dt(row["finished_at"]),
            exit_code=row["exit_code"],
            error=row["error"],
        )


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)

