from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class JobSpec:
    yaml_path: Path
    pipeline_name: str
    output_dir: Path
    input_sources: dict[str, str] = field(default_factory=dict)
    process_arg_mapping: dict[str, dict[str, str]] = field(default_factory=dict)
    backend: str = "local"
    scheduled_at: datetime | None = None


@dataclass(frozen=True)
class JobRecord:
    id: str
    spec: JobSpec
    status: JobStatus
    log_path: Path
    created_at: datetime
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
