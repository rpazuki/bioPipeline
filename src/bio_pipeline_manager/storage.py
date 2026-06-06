from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable

from bio_pipeline_manager.models import JobRecord, JobSpec, JobStatus, as_utc, utc_now


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
                    process_arg_mapping TEXT NOT NULL DEFAULT '{}',
                    backend TEXT NOT NULL,
                    status TEXT NOT NULL,
                    log_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    scheduled_at TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    exit_code INTEGER,
                    error TEXT,
                    pid INTEGER,
                    parent_job_id TEXT,
                    job_name TEXT NOT NULL DEFAULT '',
                    stage TEXT NOT NULL DEFAULT '',
                    matrix_key TEXT NOT NULL DEFAULT '{}',
                    depends_on TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_groups (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    definition TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    scheduled_at TEXT
                )
                """
            )
            # Migrate pre-existing databases that lack newer columns.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
            if "pid" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN pid INTEGER")
            if "process_arg_mapping" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN process_arg_mapping TEXT NOT NULL DEFAULT '{}'")
            if "updated_at" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN updated_at TEXT")
                conn.execute("UPDATE jobs SET updated_at = created_at WHERE updated_at IS NULL")
            if "parent_job_id" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN parent_job_id TEXT")
            if "job_name" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN job_name TEXT NOT NULL DEFAULT ''")
            if "stage" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN stage TEXT NOT NULL DEFAULT ''")
            if "matrix_key" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN matrix_key TEXT NOT NULL DEFAULT '{}'")
            if "depends_on" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN depends_on TEXT NOT NULL DEFAULT '[]'")

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # WAL lets the worker write while readers (the API) keep reading;
        # busy_timeout retries instead of raising "database is locked".
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def create_job(self, spec: JobSpec, log_path: str | Path) -> JobRecord:
        job_id = uuid.uuid4().hex
        created_at = utc_now()
        spec = JobSpec(
            yaml_path=spec.yaml_path,
            pipeline_name=spec.pipeline_name,
            output_dir=spec.output_dir,
            input_sources=spec.input_sources,
            process_arg_mapping=spec.process_arg_mapping,
            backend=spec.backend,
            scheduled_at=as_utc(spec.scheduled_at),
            parent_job_id=spec.parent_job_id,
            job_name=spec.job_name,
            stage=spec.stage,
            matrix_key=spec.matrix_key,
            depends_on=spec.depends_on,
        )
        record = JobRecord(
            id=job_id,
            spec=spec,
            status=JobStatus.QUEUED,
            log_path=Path(log_path),
            created_at=created_at,
            updated_at=created_at,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, yaml_path, pipeline_name, output_dir, input_sources, process_arg_mapping,
                    backend, status, log_path, created_at, updated_at, scheduled_at,
                    parent_job_id, job_name, stage, matrix_key, depends_on
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    str(spec.yaml_path),
                    spec.pipeline_name,
                    str(spec.output_dir),
                    json.dumps(spec.input_sources, sort_keys=True),
                    json.dumps(spec.process_arg_mapping, sort_keys=True),
                    spec.backend,
                    record.status.value,
                    str(record.log_path),
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    spec.scheduled_at.isoformat() if spec.scheduled_at else None,
                    spec.parent_job_id,
                    spec.job_name,
                    spec.stage,
                    json.dumps(spec.matrix_key, sort_keys=True),
                    json.dumps(spec.depends_on),
                ),
            )
        return record

    def claim_job(self, job_id: str) -> bool:
        """Atomically move a job from QUEUED to RUNNING.

        Returns True only for the caller that won the claim, so a worker
        thread and a manual run-due call can never run the same job twice.
        """
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = ?, started_at = COALESCE(started_at, ?), updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (JobStatus.RUNNING.value, utc_now().isoformat(), utc_now().isoformat(), job_id, JobStatus.QUEUED.value),
            )
            return cursor.rowcount == 1

    def set_pid(self, job_id: str, pid: int | None) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE jobs SET pid = ?, updated_at = ? WHERE id = ?", (pid, utc_now().isoformat(), job_id))

    def cancel_job(self, job_id: str, *, reason: str = "Cancelled by user") -> JobRecord:
        job = self.get_job(job_id)
        if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            raise ValueError(f"Cannot cancel job in status '{job.status}'")
        return self.update_status(
            job_id,
            JobStatus.CANCELLED,
            finished_at=utc_now(),
            error=reason,
        )

    def delete_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job.status == JobStatus.RUNNING:
            raise ValueError("Cannot delete a running job")
        with self.connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        try:
            if job.log_path.exists():
                job.log_path.unlink()
        except OSError:
            pass

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

    def has_active_jobs(self) -> bool:
        """True if any job is currently RUNNING (used to gate package installs)."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM jobs WHERE status = ? LIMIT 1", (JobStatus.RUNNING.value,)
            ).fetchone()
        return row is not None

    def create_group(
        self, group_id: str, name: str, definition: str, scheduled_at: datetime | None = None
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO job_groups (id, name, definition, created_at, scheduled_at) VALUES (?, ?, ?, ?, ?)",
                (
                    group_id,
                    name,
                    definition,
                    utc_now().isoformat(),
                    scheduled_at.isoformat() if scheduled_at else None,
                ),
            )

    def get_group(self, group_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM job_groups WHERE id = ?", (group_id,)).fetchone()
        return dict(row) if row else None

    def list_group_ids(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT id FROM job_groups ORDER BY created_at DESC").fetchall()
        return [row["id"] for row in rows]

    def list_jobs_by_parent(self, parent_job_id: str) -> list[JobRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE parent_job_id = ? ORDER BY created_at ASC",
                (parent_job_id,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_parent_ids(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT parent_job_id, MIN(created_at) AS first_created FROM jobs "
                "WHERE parent_job_id IS NOT NULL GROUP BY parent_job_id ORDER BY first_created DESC"
            ).fetchall()
        return [row["parent_job_id"] for row in rows]

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
                    updated_at = ?,
                    started_at = COALESCE(?, started_at),
                    finished_at = COALESCE(?, finished_at),
                    exit_code = COALESCE(?, exit_code),
                    error = COALESCE(?, error)
                WHERE id = ?
                """,
                (
                    status.value,
                    utc_now().isoformat(),
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
        row_keys = row.keys()
        process_arg_mapping = (
            json.loads(row["process_arg_mapping"])
            if "process_arg_mapping" in row_keys and row["process_arg_mapping"]
            else {}
        )
        spec = JobSpec(
            yaml_path=Path(row["yaml_path"]),
            pipeline_name=row["pipeline_name"],
            output_dir=Path(row["output_dir"]),
            input_sources=json.loads(row["input_sources"]),
            process_arg_mapping=process_arg_mapping,
            backend=row["backend"],
            scheduled_at=scheduled_at,
            parent_job_id=row["parent_job_id"] if "parent_job_id" in row_keys else None,
            job_name=row["job_name"] if "job_name" in row_keys and row["job_name"] else "",
            stage=row["stage"] if "stage" in row_keys and row["stage"] else "",
            matrix_key=json.loads(row["matrix_key"]) if "matrix_key" in row_keys and row["matrix_key"] else {},
            depends_on=json.loads(row["depends_on"]) if "depends_on" in row_keys and row["depends_on"] else [],
        )
        return JobRecord(
            id=row["id"],
            spec=spec,
            status=JobStatus(row["status"]),
            log_path=Path(row["log_path"]),
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]) if "updated_at" in row_keys and row["updated_at"] else _parse_dt(row["created_at"]),
            started_at=_parse_dt(row["started_at"]),
            finished_at=_parse_dt(row["finished_at"]),
            exit_code=row["exit_code"],
            error=row["error"],
            pid=row["pid"],
        )


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)
