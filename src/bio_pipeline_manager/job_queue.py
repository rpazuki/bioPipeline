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

from bio_pipeline_manager.job_definition import (
    JobDefinitionError,
    cell_matrix_key,
    iter_cells,
    materialize_stage,
    parse_job_definition,
)
from bio_pipeline_manager.models import (
    TERMINAL_FAILURE_STATUSES,
    JobRecord,
    JobSpec,
    JobStatus,
    utc_now,
)
from bio_pipeline_manager.runner import LocalSubprocessRunner
from bio_pipeline_manager.storage import JobStore


def _safe_resolve(resolver: Callable[[str], Path], name: str) -> Path:
    try:
        return resolver(name)
    except Exception:  # noqa: BLE001 - placeholder tasks never run; path is cosmetic
        return Path(name)


class JobQueue:
    """Small queue facade around the SQLite store and local runner."""

    def __init__(
        self,
        store: JobStore,
        logs_dir: str | Path,
        *,
        runner: LocalSubprocessRunner | None = None,
        yaml_resolver: Callable[[str], Path] | None = None,
    ):
        self.store = store
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.runner = runner or LocalSubprocessRunner(store)
        # Used to resolve a stage's pipeline_yaml name when materialising lazily.
        self.yaml_resolver: Callable[[str], Path] = yaml_resolver or Path

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
        yaml_resolver: Callable[[str], Path] | None = None,
        scheduled_at: datetime | None = None,
    ) -> tuple[str, list[JobRecord]]:
        """Queue a Job Definition as one parent group, materialising lazily.

        Only stages that are immediately eligible (no unmet ``needs``) are
        materialised now; downstream stages are materialised by ``run_due`` once
        their upstream stages in the same cell have succeeded — so a fan-out
        source produced by an upstream stage need not exist at submit time.
        Returns ``(parent_job_id, initial_task_records)``.
        """
        # Validate up-front so a bad definition fails the submit, not later.
        job_def = parse_job_definition(text)
        if yaml_resolver is not None:
            self.yaml_resolver = yaml_resolver

        # Validate static pipeline_yaml references now (raises on out-of-store
        # paths) so a bad reference fails the submit cleanly instead of later.
        for stage in job_def.stages:
            pipeline_yaml = stage["pipeline_yaml"]
            if "{" not in pipeline_yaml:
                self.yaml_resolver(pipeline_yaml)

        parent_job_id = uuid.uuid4().hex
        self.store.create_group(parent_job_id, job_def.name, text, scheduled_at)
        return parent_job_id, self._materialize_ready(parent_job_id)

    def _materialize_ready(self, parent_job_id: str) -> list[JobRecord]:
        """Create Tasks for every stage that has become eligible but isn't yet
        materialised. Idempotent; safe to call repeatedly from ``run_due``."""
        group = self.store.get_group(parent_job_id)
        if group is None:
            return []
        job_def = parse_job_definition(group["definition"])
        scheduled_at = (
            datetime.fromisoformat(group["scheduled_at"]) if group.get("scheduled_at") else None
        )

        # Snapshot existing tasks, indexed by (cell key, stage name).
        by_cell_stage: dict[tuple[str, str], list[JobRecord]] = defaultdict(list)
        for record in self.store.list_jobs_by_parent(parent_job_id):
            by_cell_stage[(json.dumps(record.spec.matrix_key, sort_keys=True), record.spec.stage)].append(record)
        # Persistent record of stages already materialised, so a stage is never
        # re-created (resurrected) after its Task rows are cancelled+deleted.
        materialized = self.store.materialized_stages(parent_job_id)

        created: list[JobRecord] = []
        for cell in iter_cells(job_def):
            matrix_key = cell_matrix_key(cell)
            key_json = json.dumps(matrix_key, sort_keys=True)
            for stage in job_def.stages:
                stage_name = stage["name"]
                if (key_json, stage_name) in materialized or by_cell_stage.get((key_json, stage_name)):
                    # Already materialised (even if its tasks were since removed).
                    self.store.mark_stage_materialized(parent_job_id, key_json, stage_name)
                    continue

                needs = list(stage.get("needs", []) or [])
                upstream: list[JobRecord] = []
                eligible = True
                for need in needs:
                    need_records = by_cell_stage.get((key_json, need))
                    if not need_records:
                        eligible = False  # upstream not materialised yet
                        break
                    upstream.extend(need_records)
                if not eligible:
                    continue
                upstream_ids = [r.id for r in upstream]
                if needs:
                    statuses = {record.status for record in upstream}
                    if statuses & TERMINAL_FAILURE_STATUSES:
                        # An upstream will never succeed: settle this stage as a
                        # single BLOCKED placeholder so it is visible and not retried.
                        new_records = [
                            self._materialize_placeholder(
                                parent_job_id, job_def, cell, stage, upstream_ids, scheduled_at,
                                JobStatus.BLOCKED, "Upstream dependency did not succeed",
                            )
                        ]
                        by_cell_stage[(key_json, stage_name)].extend(new_records)
                        self.store.mark_stage_materialized(parent_job_id, key_json, stage_name)
                        created.extend(new_records)
                        continue
                    if statuses != {JobStatus.SUCCEEDED}:
                        continue  # still running/queued; wait

                new_records = self._materialize_one(
                    parent_job_id, job_def, cell, stage, upstream_ids, scheduled_at
                )
                by_cell_stage[(key_json, stage_name)].extend(new_records)
                self.store.mark_stage_materialized(parent_job_id, key_json, stage_name)
                created.extend(new_records)
        return created

    def _materialize_one(
        self,
        parent_job_id: str,
        job_def,
        cell: dict,
        stage: dict,
        depends_on: list[str],
        scheduled_at: datetime | None,
    ) -> list[JobRecord]:
        try:
            tasks = materialize_stage(job_def, cell, stage)
        except JobDefinitionError as exc:
            # Eligible (upstream succeeded) but the fan-out source still can't be
            # read — surface a single FAILED placeholder so it settles and shows.
            return [
                self._materialize_placeholder(
                    parent_job_id, job_def, cell, stage, depends_on, scheduled_at,
                    JobStatus.FAILED, str(exc),
                )
            ]

        records: list[JobRecord] = []
        for task in tasks:
            spec = self._spec_from_task(parent_job_id, task, depends_on, scheduled_at)
            records.append(self.submit(spec))
        return records

    def _materialize_placeholder(
        self, parent_job_id, job_def, cell, stage, depends_on, scheduled_at, status, error
    ) -> JobRecord:
        """Create one non-running placeholder Task (FAILED/BLOCKED) for a stage
        that became eligible but cannot run, so it is visible in the rollup."""
        placeholder = materialize_stage(job_def, cell, stage, lenient=True)[0]
        spec = self._spec_from_task(parent_job_id, placeholder, depends_on, scheduled_at, safe=True)
        record = self.submit(spec)
        return self.store.update_status(record.id, status, finished_at=utc_now(), error=error)

    def _spec_from_task(self, parent_job_id, task, depends_on, scheduled_at, *, safe: bool = False) -> JobSpec:
        yaml_path = _safe_resolve(self.yaml_resolver, task.pipeline_yaml) if safe else self.yaml_resolver(task.pipeline_yaml)
        return JobSpec(
            yaml_path=yaml_path,
            pipeline_name=task.pipeline_name,
            output_dir=Path(task.output_dir),
            input_sources=task.input_sources,
            input_arg_mapping=task.input_arg_mapping,
            process_arg_mapping=task.process_arg_mapping,
            output_path_mapping=task.output_path_mapping,
            scheduled_at=scheduled_at,
            parent_job_id=parent_job_id,
            job_name=task.job_name,
            stage=task.stage,
            matrix_key=task.matrix_key,
            depends_on=depends_on,
        )

    def cancel(self, job_id: str) -> JobRecord:
        """Cancel a job, killing its subprocess if it is already running."""
        job = self.store.get_job(job_id)
        # Persist CANCELLED *before* signalling the process. On Windows SIGTERM
        # terminates it immediately, so the runner's process.wait() can return
        # and re-read the status the instant the signal lands. Committing the
        # cancel first guarantees that read sees CANCELLED rather than RUNNING,
        # so the runner never clobbers it with FAILED.
        record = self.store.cancel_job(job_id)
        if job.status == JobStatus.RUNNING and job.pid:
            try:
                os.kill(job.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        return record

    def delete(self, job_id: str) -> None:
        self.store.delete_job(job_id)

    def rewind(self, job_id: str) -> JobRecord:
        job = self.store.get_job(job_id)
        spec = JobSpec(
            yaml_path=job.spec.yaml_path,
            pipeline_name=job.spec.pipeline_name,
            output_dir=job.spec.output_dir,
            input_sources=job.spec.input_sources,
            input_arg_mapping=job.spec.input_arg_mapping,
            process_arg_mapping=job.spec.process_arg_mapping,
            output_path_mapping=job.spec.output_path_mapping,
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
        # Materialise any stages whose upstreams have just succeeded, so newly
        # eligible Tasks (e.g. a collate that fans out over preprocess output)
        # appear before we select what to run.
        for group_id in self.store.list_group_ids():
            try:
                self._materialize_ready(group_id)
            except Exception:  # noqa: BLE001 - a bad group must not stall the queue
                pass

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
