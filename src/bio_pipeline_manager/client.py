from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class PipelineClient:
    """Small HTTP client for notebooks and scripts."""

    base_url: str = "http://127.0.0.1:8000"

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def list_yamls(self) -> list[dict[str, Any]]:
        return self._request("GET", "/yamls")

    def get_yaml(self, name: str) -> dict[str, Any]:
        return self._request("GET", f"/yamls/{name}")

    def save_yaml(self, name: str, content: str, *, overwrite: bool = True) -> dict[str, Any]:
        return self._request(
            "POST",
            "/yamls",
            {
                "name": name,
                "content": content,
                "overwrite": overwrite,
            },
        )

    def validate_yaml(self, content: str, *, imports: bool = False) -> dict[str, Any]:
        return self._request(
            "POST",
            "/yamls/validate",
            {
                "content": content,
                "imports": imports,
            },
        )

    def submit(
        self,
        yaml_name: str,
        pipeline_name: str,
        output_dir: str,
        *,
        input_sources: dict[str, str] | None = None,
        process_arg_mapping: dict[str, dict[str, str]] | None = None,
        scheduled_at: str | None = None,
        backend: str = "local",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/jobs",
            {
                "yaml_name": yaml_name,
                "pipeline_name": pipeline_name,
                "output_dir": output_dir,
                "input_sources": input_sources or {},
                "process_arg_mapping": process_arg_mapping or {},
                "scheduled_at": scheduled_at,
                "backend": backend,
            },
        )

    def list_jobs(self) -> list[dict[str, Any]]:
        return self._request("GET", "/jobs")

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/jobs/{job_id}")

    def logs(self, job_id: str) -> str:
        return self._request("GET", f"/jobs/{job_id}/logs")["log"]

    def run_due(self, *, parallel: int = 1) -> list[dict[str, Any]]:
        return self._request("POST", f"/jobs/run-due?parallel={parallel}")

    def cancel(self, job_id: str) -> dict[str, Any]:
        return self._request("POST", f"/jobs/{job_id}/cancel")

    # --- Job Definitions (multi-task) ------------------------------------- #
    def preview_definition(self, content: str) -> dict[str, Any]:
        return self._request("POST", "/job-definitions/preview", {"content": content})

    def submit_definition(self, content: str, *, scheduled_at: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/job-definitions", {"content": content, "scheduled_at": scheduled_at})

    def list_definitions(self) -> list[dict[str, Any]]:
        return self._request("GET", "/job-definitions")

    def get_definition(self, parent_job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/job-definitions/{parent_job_id}")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url.rstrip("/") + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                content = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8")
            raise RuntimeError(f"{exc.code} {exc.reason}: {detail}") from exc
        return json.loads(content) if content else None

