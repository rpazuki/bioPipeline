from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from bio_pipeline_manager.models import JobRecord, JobSpec
from bio_pipeline_manager.runner import LocalSubprocessRunner
from bio_pipeline_manager.storage import JobStore


class JobQueue:
    """Small queue facade around the SQLite store and local runner."""

    def __init__(self, store: JobStore, logs_dir: str | Path):
        self.store = store
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def submit(self, spec: JobSpec) -> JobRecord:
        provisional_log_path = self.logs_dir / "pending.log"
        record = self.store.create_job(spec, provisional_log_path)
        final_log_path = self.logs_dir / f"{record.id}.log"
        with self.store.connect() as conn:
            conn.execute("UPDATE jobs SET log_path = ? WHERE id = ?", (str(final_log_path), record.id))
        return self.store.get_job(record.id)

    def run_due(self, *, parallel: int = 1) -> list[JobRecord]:
        due = self.store.list_due_jobs(limit=parallel)
        if not due:
            return []

        runner = LocalSubprocessRunner(self.store)
        if parallel <= 1:
            return [runner.run(job.id) for job in due]

        results: list[JobRecord] = []
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = [executor.submit(runner.run, job.id) for job in due]
            for future in as_completed(futures):
                results.append(future.result())
        return results

