"""Recurring schedules for plain (admin-submitted) jobs.

The researcher-facing :mod:`bio_pipeline_manager.recurring_schedule` repeats a
*published job* (cloning uploaded inputs each time). This module is its admin
counterpart: it repeats a single submitted **job** — a stored ``JobSubmitRequest``
payload that points at server-side paths — every interval until its end rule.

It deliberately reuses the interval/end-rule helpers (``interval_delta``,
``advance``, ``END_MODES``) from the published-job module so both kinds of
schedule step forward and settle identically; only the payload and the firing
action differ.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from bio_pipeline_manager.models import JobSpec, utc_now
from bio_pipeline_manager.recurring_schedule import (
    END_MODES,
    RecurringScheduleError,
    advance,
    interval_delta,
)


@dataclass(frozen=True)
class RecurringJobRecord:
    id: str
    name: str
    payload: dict[str, Any]
    every_n: int
    unit: str
    ends_mode: str
    ends_count: int
    ends_at: datetime | None
    next_run_at: datetime
    runs_done: int
    active: bool
    created_at: datetime
    last_run_at: datetime | None = None


class RecurringJobStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recurring_jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL DEFAULT '{}',
                    every_n INTEGER NOT NULL,
                    unit TEXT NOT NULL,
                    ends_mode TEXT NOT NULL DEFAULT 'never',
                    ends_count INTEGER NOT NULL DEFAULT 0,
                    ends_at TEXT,
                    next_run_at TEXT NOT NULL,
                    runs_done INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_run_at TEXT
                )
                """
            )

    def create(
        self,
        *,
        name: str,
        payload: dict[str, Any],
        every_n: int,
        unit: str,
        ends_mode: str,
        ends_count: int,
        ends_at: datetime | None,
        first_run_at: datetime,
    ) -> RecurringJobRecord:
        if ends_mode not in END_MODES:
            raise RecurringScheduleError(f"Unknown end mode '{ends_mode}'")
        interval_delta(every_n, unit)  # validate
        if ends_mode == "count" and ends_count < 1:
            raise RecurringScheduleError("End-after-runs count must be at least 1")
        if ends_mode == "until" and ends_at is None:
            raise RecurringScheduleError("End-on-date requires a date")
        record_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO recurring_jobs (
                    id, name, payload, every_n, unit, ends_mode, ends_count, ends_at,
                    next_run_at, runs_done, active, created_at, last_run_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, NULL)
                """,
                (
                    record_id,
                    name,
                    json.dumps(payload, sort_keys=True),
                    every_n,
                    unit,
                    ends_mode,
                    ends_count,
                    ends_at.isoformat() if ends_at else None,
                    first_run_at.isoformat(),
                    utc_now().isoformat(),
                ),
            )
        return self.get(record_id)

    def get(self, record_id: str) -> RecurringJobRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM recurring_jobs WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(f"Recurring job not found: {record_id}")
        return _from_row(row)

    def list(self) -> list[RecurringJobRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM recurring_jobs ORDER BY created_at DESC").fetchall()
        return [_from_row(row) for row in rows]

    def list_due(self, now: datetime) -> list[RecurringJobRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM recurring_jobs WHERE active = 1 AND next_run_at <= ? ORDER BY next_run_at",
                (now.isoformat(),),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def record_fired(
        self, record_id: str, *, next_run_at: datetime, runs_done: int, active: bool, last_run_at: datetime
    ) -> RecurringJobRecord:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE recurring_jobs
                SET next_run_at = ?, runs_done = ?, active = ?, last_run_at = ?
                WHERE id = ?
                """,
                (next_run_at.isoformat(), runs_done, 1 if active else 0, last_run_at.isoformat(), record_id),
            )
        return self.get(record_id)

    def set_active(self, record_id: str, active: bool) -> RecurringJobRecord:
        self.get(record_id)
        with self.connect() as conn:
            conn.execute("UPDATE recurring_jobs SET active = ? WHERE id = ?", (1 if active else 0, record_id))
        return self.get(record_id)

    def delete(self, record_id: str) -> None:
        self.get(record_id)
        with self.connect() as conn:
            conn.execute("DELETE FROM recurring_jobs WHERE id = ?", (record_id,))


def fire_recurring_job(
    *,
    queue: Any,
    yaml_resolver: Callable[[str], Path],
    jobs: RecurringJobStore,
    record: RecurringJobRecord,
) -> None:
    """Submit one occurrence of a recurring job, then advance/settle the schedule.

    A bad YAML reference deactivates the schedule rather than erroring forever.
    """
    payload = record.payload
    try:
        spec = JobSpec(
            yaml_path=yaml_resolver(payload["yaml_name"]),
            pipeline_name=payload.get("pipeline_name", ""),
            output_dir=Path(payload.get("output_dir", "")),
            input_sources=payload.get("input_sources") or {},
            input_arg_mapping=payload.get("input_arg_mapping") or {},
            process_arg_mapping=payload.get("process_arg_mapping") or {},
            output_path_mapping=payload.get("output_path_mapping") or {},
            backend=payload.get("backend", "local"),
            scheduled_at=None,  # run as soon as the worker next drains the queue
        )
    except Exception:
        jobs.set_active(record.id, False)
        return
    queue.submit(spec)
    fired_at = utc_now()
    next_run_at, runs_done, active = advance(record, fired_at)
    jobs.record_fired(record.id, next_run_at=next_run_at, runs_done=runs_done, active=active, last_run_at=fired_at)


def _from_row(row: sqlite3.Row) -> RecurringJobRecord:
    return RecurringJobRecord(
        id=row["id"],
        name=row["name"],
        payload=json.loads(row["payload"] or "{}"),
        every_n=int(row["every_n"]),
        unit=row["unit"],
        ends_mode=row["ends_mode"],
        ends_count=int(row["ends_count"]),
        ends_at=datetime.fromisoformat(row["ends_at"]) if row["ends_at"] else None,
        next_run_at=datetime.fromisoformat(row["next_run_at"]),
        runs_done=int(row["runs_done"]),
        active=bool(row["active"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        last_run_at=datetime.fromisoformat(row["last_run_at"]) if row["last_run_at"] else None,
    )
