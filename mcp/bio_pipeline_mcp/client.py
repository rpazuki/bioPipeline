"""Authenticated HTTP client for the Bio Pipeline Manager backend.

The backend authenticates with username/password and issues an opaque
server-side session as an httponly cookie (see ``backend/app/api/deps.py``). This
client logs in lazily, persists the session cookie in its jar, and transparently
re-authenticates once on a 401 so long-lived MCP sessions survive cookie
expiry.
"""

from __future__ import annotations

import threading
from typing import Any

import httpx

from .config import Settings, load_settings


class ApiError(RuntimeError):
    """A backend call failed. Message carries the HTTP status + server detail."""


class BioPipelineClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or load_settings()
        self._lock = threading.Lock()
        self._client = httpx.Client(
            base_url=self._settings.api_root,
            timeout=self._settings.timeout,
            verify=self._settings.verify_tls,
            follow_redirects=True,
        )
        self._logged_in = False

    # -- auth ------------------------------------------------------------- #
    def login(self) -> dict[str, Any]:
        creds = {
            "username": self._settings.username,
            "password": self._settings.password,
        }
        if not creds["username"] or not creds["password"]:
            raise ApiError(
                "Missing credentials: set BIO_PIPELINE_USERNAME and "
                "BIO_PIPELINE_PASSWORD in the MCP server environment."
            )
        resp = self._client.post("/auth/login", json=creds)
        if resp.status_code >= 400:
            raise ApiError(_format_error(resp))
        self._logged_in = True
        return resp.json()

    def _ensure_login(self) -> None:
        if not self._logged_in:
            with self._lock:
                if not self._logged_in:
                    self.login()

    # -- core request ----------------------------------------------------- #
    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> Any:
        """Issue an authenticated request and return parsed JSON (or None).

        ``path`` is relative to the API root (e.g. ``/jobs``). Retries once after
        re-login on a 401.
        """
        self._ensure_login()
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        resp = self._client.request(method, path, params=clean_params, json=json)
        if resp.status_code == 401:
            self._logged_in = False
            self._ensure_login()
            resp = self._client.request(method, path, params=clean_params, json=json)
        if resp.status_code >= 400:
            raise ApiError(_format_error(resp))
        if resp.status_code == 204 or not resp.content:
            return {"ok": True, "status": resp.status_code}
        ctype = resp.headers.get("content-type", "")
        if "application/json" in ctype:
            return resp.json()
        return {"content_type": ctype, "text": resp.text}

    # Convenience verbs -------------------------------------------------- #
    def get(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        return self.request("POST", path, **kw)

    def patch(self, path: str, **kw: Any) -> Any:
        return self.request("PATCH", path, **kw)

    def put(self, path: str, **kw: Any) -> Any:
        return self.request("PUT", path, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        return self.request("DELETE", path, **kw)

    def health(self) -> Any:
        """Unauthenticated health probe (lives outside the API prefix)."""
        resp = httpx.get(
            self._settings.base_url.rstrip("/") + "/health",
            timeout=self._settings.timeout,
            verify=self._settings.verify_tls,
        )
        resp.raise_for_status()
        return resp.json()


def _format_error(resp: httpx.Response) -> str:
    detail: Any
    try:
        body = resp.json()
        detail = body.get("detail", body) if isinstance(body, dict) else body
    except Exception:  # noqa: BLE001 - non-JSON error body
        detail = resp.text
    return f"HTTP {resp.status_code} {resp.reason_phrase} on {resp.request.method} {resp.request.url.path}: {detail}"
