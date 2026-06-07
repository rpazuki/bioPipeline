from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


# Statuses that mean a task will never succeed, so its dependents can never run.
TERMINAL_FAILURE_STATUSES = frozenset({JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.BLOCKED})


@dataclass(frozen=True)
class JobSpec:
    yaml_path: Path
    pipeline_name: str
    output_dir: Path
    input_sources: dict[str, str] = field(default_factory=dict)
    input_arg_mapping: dict[str, dict[str, Any]] = field(default_factory=dict)
    process_arg_mapping: dict[str, dict[str, Any]] = field(default_factory=dict)
    output_path_mapping: dict[str, Any] = field(default_factory=dict)
    backend: str = "local"
    scheduled_at: datetime | None = None
    # Job Definition grouping (empty for ad-hoc single-task submissions).
    parent_job_id: str | None = None
    job_name: str = ""
    stage: str = ""
    matrix_key: dict[str, str] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class JobRecord:
    id: str
    spec: JobSpec
    status: JobStatus
    log_path: Path
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    error: str | None = None
    pid: int | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
