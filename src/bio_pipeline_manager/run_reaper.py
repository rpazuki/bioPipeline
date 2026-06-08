"""Background delivery + cleanup for finished published-job runs.

When a run's task group reaches a terminal state the reaper packages its
outputs into a downloadable ``artifact.zip``, copies any shared-delivery outputs
onto an allowlisted share (Phase 5), then deletes the now-unneeded inputs. After
a retention window (``ttl_hours``) the whole run workspace is removed.

Runs alongside :class:`bio_pipeline_manager.worker.JobWorker` (started in the
API lifespan). Delivery state lives on disk in the workspace (an ``artifact.zip``
and a ``.reaped`` marker), so no extra database columns are needed.
"""

from __future__ import annotations

import logging
import shutil
import threading
from datetime import timedelta
from typing import Callable

from bio_pipeline_manager.models import utc_now
from bio_pipeline_manager.published_jobs import PublishedJobStore
from bio_pipeline_manager.run_workspace import RunWorkspaceStore
from bio_pipeline_manager.shared_storage import SharedStorage

logger = logging.getLogger(__name__)

_TERMINAL = {"succeeded", "failed", "partially_failed"}
_SHARED_OUTPUT_SUBDIR = "bio_pipeline_outputs"


class RunReaper:
    def __init__(
        self,
        *,
        published_jobs: PublishedJobStore,
        run_workspaces: RunWorkspaceStore,
        shared_storage: SharedStorage,
        group_status: Callable[[str], dict],
        ttl_hours: float = 24.0,
        interval: float = 5.0,
    ):
        self.published_jobs = published_jobs
        self.run_workspaces = run_workspaces
        self.shared_storage = shared_storage
        self.group_status = group_status
        self.ttl = timedelta(hours=ttl_hours)
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="run-reaper", daemon=True)
        self._thread.start()
        logger.info("Run reaper started (interval=%ss, ttl=%s)", self.interval, self.ttl)

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None
        logger.info("Run reaper stopped")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.reap_once()
            except Exception:  # keep the loop alive across failures
                logger.exception("Run reaper iteration failed")
            self._stop.wait(self.interval)

    def reap_once(self) -> None:
        for run in self.published_jobs.list_runs():
            workspace_id = run.workspace_id
            if not workspace_id or not self.run_workspaces.exists(workspace_id):
                continue
            try:
                self._process(run)
            except Exception:  # one bad run must not stall the rest
                logger.exception("Run reaper failed for run %s", run.id)

    def _process(self, run) -> None:
        workspace_id = run.workspace_id
        reaped_at = self.run_workspaces.reaped_at(workspace_id)
        if reaped_at is None:
            summary = self.group_status(run.parent_job_id)
            if summary.get("status") not in _TERMINAL:
                return  # still queued/running
            self.run_workspaces.package_outputs(workspace_id)
            self._shared_write(run)
            self.run_workspaces.clear_inputs(workspace_id)
            self.run_workspaces.mark_reaped(workspace_id)
        elif utc_now() - reaped_at > self.ttl:
            self.run_workspaces.delete(workspace_id)

    def _shared_write(self, run) -> None:
        try:
            published = self.published_jobs.get(run.published_job_id)
        except KeyError:
            return
        for field in published.fields:
            if field.get("io_role") != "output" or "shared" not in (field.get("delivery") or []):
                continue
            roots = field.get("shared_roots") or []
            if not roots:
                continue
            field_id = field["id"]
            try:
                source = self.run_workspaces.output_dir(run.workspace_id, field_id)
                if not any(source.iterdir()):
                    continue
                target = self.shared_storage.write_target(roots[0], f"{_SHARED_OUTPUT_SUBDIR}/{run.id}/{field_id}")
                shutil.copytree(source, target, dirs_exist_ok=True)
            except Exception:
                logger.exception("Shared-write failed for run %s field %s", run.id, field_id)
