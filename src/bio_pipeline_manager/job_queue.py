from __future__ import annotations

import json
import os
import signal
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from bio_pipeline_manager.job_definition import MaterializedTask, expand
from bio_pipeline_manager.models import (
    TERMINAL_FAILURE_STATUSES,
    JobRecord,
    JobSpec,
    JobStatus,
    utc_now,
)
from bio_pipeline_manager.runner import LocalSubprocessRunner
from bio_pipeline_manager.storage import JobStore


class JobQueue:
    """Small queue facade around the SQLite store and local runner."""

    def __init__(
        self,
        store: JobStore,
        logs_dir: str | Path,
        *,
        runner: LocalSubprocessRunner | None = None,
    ):
        self.store = store
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.runner = runner or LocalSubprocessRunner(store)

    def submit(self, spec: JobSpec) -> JobRecord:
        provisional_log_path = self.logs_dir / "pending.log"
        record = self.store.create_job(spec, provisional_log_path)
        final_log_path = self.logs_dir / f"{record.id}.log"
        with self.store.connect() as conn:
            conn.execute("UPDATE jobs SET log_path = ? WHERE id = ?", (str(final_log_path), record.id))
        return self.store.get_job(record.id)

    def submit_definition(
        self,
        text: str,
        *,
        yaml_resolver: Callable[[str], Path],
        scheduled_at: datetime | None = None,
    ) -> tuple[str, list[JobRecord]]:
        """Expand a Job Definition and queue its Tasks as one parent group.

        Within each matrix cell, a stage's Tasks depend on every Task of the
        stages named in its ``needs`` (filesystem hand-off between pipelines).
        Returns ``(parent_job_id, task_records)``.
        """
        tasks: list[MaterializedTask] = expand(text)
        parent_job_id = uuid.uuid4().hex

        stage_order = {name: i for i, name in enumerate(dict.fromkeys(t.stage for t in tasks))}
        groups: dict[str, list[MaterializedTask]] = defaultdict(list)
        for task in tasks:
            groups[json.dumps(task.matrix_key, sort_keys=True)].append(task)

        records: list[JobRecord] = []
        for group in groups.values():
            group.sort(key=lambda t: (stage_order[t.stage], t.item_index))
            # Track the queued ids per stage so dependents can reference them.
            stage_ids: dict[str, list[str]] = defaultdict(list)
            for task in group:
                depends_on: list[str] = []
                for need in task.needs:
                    depends_on.extend(stage_ids.get(need, []))
                spec = JobSpec(
                    yaml_path=yaml_resolver(task.pipeline_yaml),
                    pipeline_name=task.pipeline_name,
                    output_dir=Path(task.output_dir),
                    input_sources=task.input_sources,
                    process_arg_mapping=task.process_arg_mapping,
                    scheduled_at=scheduled_at,
                    parent_job_id=parent_job_id,
                    job_name=task.job_name,
                    stage=task.stage,
                    matrix_key=task.matrix_key,
                    depends_on=depends_on,
                )
                record = self.submit(spec)
                stage_ids[task.stage].append(record.id)
                records.append(record)
        return parent_job_id, records

    def cancel(self, job_id: str) -> JobRecord:
        """Cancel a job, killing its subprocess if it is already running."""
        job = self.store.get_job(job_id)
        if job.status == JobStatus.RUNNING and job.pid:
            try:
                os.kill(job.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        return self.store.cancel_job(job_id)

    def delete(self, job_id: str) -> None:
        self.store.delete_job(job_id)

    def rewind(self, job_id: str) -> JobRecord:
        job = self.store.get_job(job_id)
        spec = JobSpec(
            yaml_path=job.spec.yaml_path,
            pipeline_name=job.spec.pipeline_name,
            output_dir=job.spec.output_dir,
            input_sources=job.spec.input_sources,
            process_arg_mapping=job.spec.process_arg_mapping,
            backend=job.spec.backend,
            scheduled_at=datetime.now(timezone.utc),
        )
        return self.submit(spec)

    def _select_runnable(self, candidates: list[JobRecord]) -> list[JobRecord]:
        """Filter QUEUED tasks by dependency readiness.

        A task with no dependencies is always runnable. A task whose upstream
        dependencies have all succeeded is runnable. A task with any failed /
        cancelled / blocked upstream is moved to BLOCKED. A task still waiting on
        running/queued upstream is skipped this round.
        """
        runnable: list[JobRecord] = []
        for job in candidates:
            deps = job.spec.depends_on
            if not deps:
                runnable.append(job)
                continue
            dep_records = [self.store.get_job(dep) for dep in deps]
            if any(dep.status in TERMINAL_FAILURE_STATUSES for dep in dep_records):
                self.store.update_status(
                    job.id,
                    JobStatus.BLOCKED,
                    finished_at=utc_now(),
                    error="Upstream dependency did not succeed",
                )
                continue
            if all(dep.status == JobStatus.SUCCEEDED for dep in dep_records):
                runnable.append(job)
        return runnable

    def run_due(self, *, parallel: int = 1) -> list[JobRecord]:
        candidates = self.store.list_due_jobs()
        runnable = self._select_runnable(candidates)
        if not runnable:
            return []

        if parallel >= 1:
            runnable = runnable[:parallel]

        runner = self.runner
        if parallel <= 1:
            return [runner.run(job.id) for job in runnable]

        results: list[JobRecord] = []
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = [executor.submit(runner.run, job.id) for job in runnable]
            for future in as_completed(futures):
                results.append(future.result())
        return results

    def group_status(self, parent_job_id: str) -> dict:
        """Aggregate rollup over a parent group's Tasks."""
        children = self.store.list_jobs_by_parent(parent_job_id)
        counts: dict[str, int] = defaultdict(int)
        for child in children:
            counts[child.status.value] += 1
        total = len(children)
        if total == 0:
            rollup = "unknown"
        elif counts.get("running") or counts.get("queued"):
            rollup = "running" if counts.get("running") else "queued"
        elif counts.get("failed") or counts.get("blocked") or counts.get("cancelled"):
            rollup = "partially_failed" if counts.get("succeeded") else "failed"
        else:
            rollup = "succeeded"
        return {
            "parent_job_id": parent_job_id,
            "job_name": children[0].spec.job_name if children else "",
            "total": total,
            "counts": dict(counts),
            "status": rollup,
            "tasks": children,
        }
