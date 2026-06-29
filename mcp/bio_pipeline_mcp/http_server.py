"""Streamable-HTTP transport for the Bio Pipeline MCP server (remote connector).

Same protocol, same 71 tools as the stdio entry point ([`server.py`](server.py))
— only the *transport* changes. This is what a cloud host (Cowork / claude.ai)
needs, since it can't spawn a local subprocess: it reaches the server over the
network instead.

Three additions over stdio:
  1. Transport — serve the FastMCP app over streamable HTTP via uvicorn.
  2. Deployment — bind a host/port; expose it at a reachable URL (tunnel/proxy).
  3. Endpoint auth — a shared-secret bearer token guards every request, because
     the endpoint now lives on a network rather than a trusted local pipe.

Run it with the ``bio-pipeline-mcp-http`` console script (or
``python -m bio_pipeline_mcp.http_server``). Configure via the
``BIO_PIPELINE_MCP_*`` env vars (see ``.env.example``).
"""

from __future__ import annotations

import hmac
import logging
import sys

import uvicorn

from .config import HttpSettings, load_http_settings
from .server import mcp

logger = logging.getLogger("bio_pipeline_mcp.http")

# Unauthenticated liveness probe (handy for tunnels, proxies, uptime checks).
_HEALTH_PATH = "/healthz"


class BearerAuthMiddleware:
    """Pure-ASGI guard requiring ``Authorization: Bearer <token>``.

    No-op when no token is configured (e.g. loopback dev). The health path is
    always allowed through without auth.
    """

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("path") == _HEALTH_PATH:
            await _send_json(send, 200, b'{"status":"ok"}')
            return
        if self.token:
            provided = _header(scope, b"authorization")
            if not hmac.compare_digest(provided, f"Bearer {self.token}"):
                await _send_json(
                    send,
                    401,
                    b'{"error":"unauthorized"}',
                    extra_headers=[(b"www-authenticate", b"Bearer")],
                )
                return
        await self.app(scope, receive, send)


def _header(scope, name: bytes) -> str:
    for key, value in scope.get("headers") or []:
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


async def _send_json(send, status: int, body: bytes, extra_headers=None) -> None:
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    headers.extend(extra_headers or [])
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def build_app(settings: HttpSettings):
    """Apply HTTP settings to the FastMCP instance and return the guarded ASGI app."""
    mcp.settings.host = settings.host
    mcp.settings.port = settings.port
    mcp.settings.streamable_http_path = settings.path
    mcp.settings.stateless_http = settings.stateless
    return BearerAuthMiddleware(mcp.streamable_http_app(), settings.auth_token)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = load_http_settings()

    if not settings.auth_token and not settings.is_loopback and not settings.allow_insecure:
        logger.error(
            "Refusing to bind %s:%s with no BIO_PIPELINE_MCP_AUTH_TOKEN. Set a "
            "token, bind to 127.0.0.1, or set BIO_PIPELINE_MCP_ALLOW_INSECURE=true.",
            settings.host,
            settings.port,
        )
        sys.exit(2)
    if not settings.auth_token:
        logger.warning(
            "Starting WITHOUT endpoint auth (no token). Only safe on a trusted/"
            "loopback interface or behind an authenticating proxy/tunnel."
        )

    app = build_app(settings)
    logger.info(
        "Bio Pipeline MCP (streamable-http) at http://%s:%s%s  [stateless=%s, auth=%s]",
        settings.host,
        settings.port,
        settings.path,
        settings.stateless,
        "on" if settings.auth_token else "off",
    )
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
