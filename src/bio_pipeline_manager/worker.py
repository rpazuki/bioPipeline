from __future__ import annotations

import logging
import threading

from bio_pipeline_manager.job_queue import JobQueue

logger = logging.getLogger(__name__)


class JobWorker:
    """Background poller that runs due jobs off the request path.

    The API process starts one of these; it periodically drains due jobs so
    execution no longer blocks an HTTP request and scheduled jobs fire on
    their own. Job claiming is atomic in the store, so running this alongside
    a manual ``run-due`` call is safe.
    """

    def __init__(self, queue: JobQueue, *, interval: float = 2.0, parallel: int = 1):
        self.queue = queue
        self.interval = interval
        self.parallel = parallel
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="job-worker", daemon=True)
        self._thread.start()
        logger.info("Job worker started (interval=%ss, parallel=%s)", self.interval, self.parallel)

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None
        logger.info("Job worker stopped")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.queue.run_due(parallel=self.parallel)
            except Exception:  # keep the loop alive across job failures
                logger.exception("Job worker iteration failed")
            self._stop.wait(self.interval)
