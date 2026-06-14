"""Recurring schedules for published-job runs.

A researcher can ask a published job to run again on a fixed interval ("every N
minutes / hours / days / weeks") until a date, after a number of runs, or
indefinitely. A schedule captures everything needed to replay the job
unattended — the field values, the file bindings, and a *template workspace*
holding a private copy of the originally-uploaded inputs — so each occurrence
clones fresh inputs into its own workspace and writes its own outputs.

:class:`RecurringScheduleStore` persists schedules (SQLite, in ``state.sqlite``);
:class:`RecurringScheduler` is the background poller that fires due ones. Firing
itself is delegated to a caller-supplied callback so this module stays free of
FastAPI / runtime wiring.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from bio_pipeline_manager.models import utc_now

logger = logging.getLogger(__name__)

UNIT_SECONDS = {
    "minutes": 60,
    "hours": 3600,
    "days": 86400,
    "weeks": 604800,
}
END_MODES = {"never", "count", "until"}


class RecurringScheduleError(ValueError):
    pass


def interval_delta(every_n: int, unit: str) -> timedelta:
    if unit not in UNIT_SECONDS:
        raise RecurringScheduleError(f"Unknown interval unit '{unit}'")
    if every_n < 1:
        raise RecurringScheduleError("Interval must be at least 1")
    return timedelta(seconds=every_n * UNIT_SECONDS[unit])


@dataclass(frozen=True)
class RecurringScheduleRecord:
    id: str
    user_id: str
    published_job_id: str
    published_version: int
    values: dict[str, Any]
    file_bindings: dict[str, Any]
    template_workspace_id: str
    every_n: int
    unit: str
    ends_mode: str
    ends_count: int
    ends_at: datetime | None
    next_run_at: datetime
    runs_done: int
    active: bool
    created_at: datetime
    last_run_at: datetime | None = field(default=None)


class RecurringScheduleStore:
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
                CREATE TABLE IF NOT EXISTS recurring_schedules (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    published_job_id TEXT NOT NULL,
                    published_version INTEGER NOT NULL,
                    field_values TEXT NOT NULL DEFAULT '{}',
                    file_bindings TEXT NOT NULL DEFAULT '{}',
                    template_workspace_id TEXT NOT NULL DEFAULT '',
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
        user_id: str,
        published_job_id: str,
        published_version: int,
        values: dict[str, Any],
        file_bindings: dict[str, Any],
        template_workspace_id: str,
        every_n: int,
        unit: str,
        ends_mode: str,
        ends_count: int,
        ends_at: datetime | None,
        first_run_at: datetime,
    ) -> RecurringScheduleRecord:
        if ends_mode not in END_MODES:
            raise RecurringScheduleError(f"Unknown end mode '{ends_mode}'")
        interval_delta(every_n, unit)  # validate
        if ends_mode == "count" and ends_count < 1:
            raise RecurringScheduleError("End-after-runs count must be at least 1")
        if ends_mode == "until" and ends_at is None:
            raise RecurringScheduleError("End-on-date requires a date")
        record_id = uuid.uuid4().hex
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO recurring_schedules (
                    id, user_id, published_job_id, published_version, field_values,
                    file_bindings, template_workspace_id, every_n, unit, ends_mode,
                    ends_count, ends_at, next_run_at, runs_done, active, created_at, last_run_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, NULL)
                """,
                (
                    record_id,
                    user_id,
                    published_job_id,
                    published_version,
                    json.dumps(values, sort_keys=True),
                    json.dumps(file_bindings, sort_keys=True),
                    template_workspace_id,
                    every_n,
                    unit,
                    ends_mode,
                    ends_count,
                    ends_at.isoformat() if ends_at else None,
                    first_run_at.isoformat(),
                    now.isoformat(),
                ),
            )
        return self.get(record_id)

    def get(self, record_id: str) -> RecurringScheduleRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM recurring_schedules WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(f"Recurring schedule not found: {record_id}")
        return _from_row(row)

    def list(self, *, user_id: str | None = None) -> list[RecurringScheduleRecord]:
        query = "SELECT * FROM recurring_schedules"
        params: tuple[Any, ...] = ()
        if user_id is not None:
            query += " WHERE user_id = ?"
            params = (user_id,)
        query += " ORDER BY created_at DESC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_from_row(row) for row in rows]

    def list_due(self, now: datetime) -> list[RecurringScheduleRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM recurring_schedules WHERE active = 1 AND next_run_at <= ? ORDER BY next_run_at",
                (now.isoformat(),),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def record_fired(
        self, record_id: str, *, next_run_at: datetime, runs_done: int, active: bool, last_run_at: datetime
    ) -> RecurringScheduleRecord:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE recurring_schedules
                SET next_run_at = ?, runs_done = ?, active = ?, last_run_at = ?
                WHERE id = ?
                """,
                (next_run_at.isoformat(), runs_done, 1 if active else 0, last_run_at.isoformat(), record_id),
            )
        return self.get(record_id)

    def set_active(self, record_id: str, active: bool) -> RecurringScheduleRecord:
        self.get(record_id)
        with self.connect() as conn:
            conn.execute(
                "UPDATE recurring_schedules SET active = ? WHERE id = ?",
                (1 if active else 0, record_id),
            )
        return self.get(record_id)

    def delete(self, record_id: str) -> None:
        self.get(record_id)
        with self.connect() as conn:
            conn.execute("DELETE FROM recurring_schedules WHERE id = ?", (record_id,))


def advance(record: RecurringScheduleRecord, now: datetime) -> tuple[datetime, int, bool]:
    """Return ``(next_run_at, runs_done, still_active)`` after one firing.

    The next time steps from the later of the planned time and ``now`` so a
    scheduler that was briefly down resumes cleanly instead of firing a burst.
    """
    runs_done = record.runs_done + 1
    delta = interval_delta(record.every_n, record.unit)
    base = record.next_run_at if record.next_run_at > now else now
    next_run_at = base + delta
    still_active = True
    if record.ends_mode == "count" and runs_done >= record.ends_count:
        still_active = False
    elif record.ends_mode == "until" and record.ends_at is not None and next_run_at > record.ends_at:
        still_active = False
    return next_run_at, runs_done, still_active


class RecurringScheduler:
    """Background poller that fires due recurring schedules via a callback."""

    def __init__(
        self,
        *,
        schedules: RecurringScheduleStore,
        fire: Callable[[RecurringScheduleRecord], None],
        interval: float = 10.0,
    ):
        self.schedules = schedules
        self.fire = fire
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="recurring-scheduler", daemon=True)
        self._thread.start()
        logger.info("Recurring scheduler started (interval=%ss)", self.interval)

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None
        logger.info("Recurring scheduler stopped")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # keep the loop alive across failures
                logger.exception("Recurring scheduler iteration failed")
            self._stop.wait(self.interval)

    def tick(self) -> None:
        for schedule in self.schedules.list_due(utc_now()):
            try:
                self.fire(schedule)
            except Exception:  # one bad schedule must not stall the rest
                logger.exception("Recurring schedule %s failed to fire", schedule.id)


def _from_row(row: sqlite3.Row) -> RecurringScheduleRecord:
    return RecurringScheduleRecord(
        id=row["id"],
        user_id=row["user_id"],
        published_job_id=row["published_job_id"],
        published_version=int(row["published_version"]),
        values=json.loads(row["field_values"] or "{}"),
        file_bindings=json.loads(row["file_bindings"] or "{}"),
        template_workspace_id=row["template_workspace_id"],
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
