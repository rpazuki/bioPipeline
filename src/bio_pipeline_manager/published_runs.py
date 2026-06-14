"""Shared execution path for a published-job run.

Both the interactive submit endpoint and the recurring scheduler funnel through
:func:`execute_published_run`, so a run is materialised the same way whether a
researcher clicked Execute or a schedule fired it: resolve I/O field values to
concrete workspace/shared paths, render the job definition, queue it, and record
the run. Keeping this in one place means scheduled and manual runs never drift.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable
from pathlib import Path

from bio_pipeline_manager.models import utc_now
from bio_pipeline_manager.published_jobs import (
    PublishedJobRecord,
    PublishedJobStore,
    PublishedRunRecord,
    render_definition,
    resolve_io,
)
from bio_pipeline_manager.recurring_schedule import (
    RecurringScheduleRecord,
    RecurringScheduleStore,
    advance,
)
from bio_pipeline_manager.run_workspace import RunWorkspaceStore
from bio_pipeline_manager.shared_storage import SharedStorage


def execute_published_run(
    *,
    published_jobs: PublishedJobStore,
    queue: Any,
    run_workspaces: RunWorkspaceStore,
    shared: SharedStorage,
    yaml_resolver: Callable[[str], Path],
    record: PublishedJobRecord,
    values: dict[str, Any],
    file_bindings: dict[str, Any],
    workspace_id: str | None,
    scheduled_at: datetime | None,
    user_id: str,
) -> PublishedRunRecord:
    resolved_values = resolve_io(
        record,
        values,
        file_bindings=file_bindings,
        workspaces=run_workspaces,
        workspace_id=workspace_id,
        shared=shared,
    )
    rendered = render_definition(record, resolved_values)
    parent_id, _records = queue.submit_definition(
        rendered,
        yaml_resolver=yaml_resolver,
        scheduled_at=scheduled_at,
    )
    return published_jobs.create_run(
        published_job_id=record.id,
        published_version=record.version,
        user_id=user_id,
        values=values,
        rendered_definition=rendered,
        parent_job_id=parent_id,
        workspace_id=workspace_id or "",
        file_bindings=file_bindings,
    )


def run_needs_workspace(record: PublishedJobRecord) -> bool:
    """True if any field writes outputs (so a per-run workspace must be created)."""
    return any(field.get("io_role") == "output" for field in record.fields)


def fire_recurring_schedule(
    *,
    published_jobs: PublishedJobStore,
    queue: Any,
    run_workspaces: RunWorkspaceStore,
    shared: SharedStorage,
    yaml_resolver: Callable[[str], Path],
    schedules: RecurringScheduleStore,
    schedule: RecurringScheduleRecord,
) -> PublishedRunRecord | None:
    """Run one occurrence of a recurring schedule, then advance/settle it.

    Each occurrence clones the schedule's retained input template into a fresh
    workspace (or creates an empty one for output-only jobs) and executes the run
    exactly as the interactive path does. ``next_run_at`` then steps forward and
    the schedule deactivates once its end rule is met. A deleted published job
    deactivates the schedule rather than erroring.
    """
    try:
        record = published_jobs.get(schedule.published_job_id)
    except KeyError:
        schedules.set_active(schedule.id, False)
        return None
    workspace_id: str | None = None
    template = schedule.template_workspace_id
    if template and run_workspaces.exists(template):
        workspace_id = run_workspaces.clone_inputs(
            template, owner_user_id=schedule.user_id, published_job_id=record.id
        ).workspace_id
    elif run_needs_workspace(record):
        workspace_id = run_workspaces.create(
            owner_user_id=schedule.user_id, published_job_id=record.id
        ).workspace_id
    run = execute_published_run(
        published_jobs=published_jobs,
        queue=queue,
        run_workspaces=run_workspaces,
        shared=shared,
        yaml_resolver=yaml_resolver,
        record=record,
        values=schedule.values,
        file_bindings=schedule.file_bindings,
        workspace_id=workspace_id,
        scheduled_at=None,
        user_id=schedule.user_id,
    )
    fired_at = utc_now()
    next_run_at, runs_done, active = advance(schedule, fired_at)
    schedules.record_fired(
        schedule.id, next_run_at=next_run_at, runs_done=runs_done, active=active, last_run_at=fired_at
    )
    return run
