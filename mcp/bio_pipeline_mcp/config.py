"""Runtime configuration for the Bio Pipeline MCP server.

Everything is read from the process environment (Claude Desktop passes these via
the ``env`` block of the server entry in ``claude_desktop_config.json``). A
``.env`` file next to the package — or in the current working directory — is
loaded first as a convenience for local runs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    """Best-effort .env loading without a hard dependency on python-dotenv."""
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for path in candidates:
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Do not override anything already provided by the real environment.
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    """Connection + credential settings for the backend API."""

    base_url: str
    api_prefix: str
    username: str
    password: str
    timeout: float
    verify_tls: bool

    @property
    def api_root(self) -> str:
        """Fully-qualified API root, e.g. ``http://127.0.0.1:8006/api/v1``."""
        return self.base_url.rstrip("/") + "/" + self.api_prefix.strip("/")


def load_settings() -> Settings:
    _load_dotenv()
    return Settings(
        base_url=os.environ.get("BIO_PIPELINE_BASE_URL", "http://127.0.0.1:8006"),
        api_prefix=os.environ.get("BIO_PIPELINE_API_PREFIX", "/api/v1"),
        username=os.environ.get("BIO_PIPELINE_USERNAME", ""),
        password=os.environ.get("BIO_PIPELINE_PASSWORD", ""),
        timeout=float(os.environ.get("BIO_PIPELINE_TIMEOUT", "60")),
        verify_tls=os.environ.get("BIO_PIPELINE_VERIFY_TLS", "true").lower()
        not in {"0", "false", "no"},
    )


def _is_true(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class HttpSettings:
    """Settings for serving the server over the streamable-HTTP transport.

    Used by the remote-connector variant (Cowork / claude.ai) — see
    ``http_server.py``. The stdio transport ignores all of these.
    """

    host: str
    port: int
    path: str
    auth_token: str
    stateless: bool
    allow_insecure: bool

    @property
    def is_loopback(self) -> bool:
        return self.host in {"127.0.0.1", "localhost", "::1"}


def load_http_settings() -> HttpSettings:
    _load_dotenv()
    return HttpSettings(
        host=os.environ.get("BIO_PIPELINE_MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("BIO_PIPELINE_MCP_PORT", "8765")),
        path=os.environ.get("BIO_PIPELINE_MCP_PATH", "/mcp"),
        # Shared-secret bearer token required on every HTTP request when set.
        auth_token=os.environ.get("BIO_PIPELINE_MCP_AUTH_TOKEN", ""),
        # Stateless is friendlier behind brokers/proxies/tunnels (no session affinity).
        stateless=_is_true(os.environ.get("BIO_PIPELINE_MCP_STATELESS", "true")),
        # Escape hatch to bind a non-loopback interface without a token (NOT advised).
        allow_insecure=_is_true(os.environ.get("BIO_PIPELINE_MCP_ALLOW_INSECURE", "false")),
    )
