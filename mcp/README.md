# Bio Pipeline Manager — MCP Server

An [MCP](https://modelcontextprotocol.io) server that exposes the Bio Pipeline
Manager HTTP API (pipelines, jobs, job definitions, published jobs, runs,
queues, recurring schedules, type library, users, packages) as tools an agent or
LLM can call — designed for **Claude Desktop** and **Cowork**.

It is a thin, authenticated client over the backend API: every tool maps to a
route under `/api/v1`. The account it logs in with decides what it can do —
an **admin** account unlocks the whole surface; a **researcher** (`user`)
account exposes only the catalog / run / saved-value tools.

> **Self-contained.** This folder shares no code with the rest of the repo (it
> imports nothing from `backend/` or `src/`); its only dependencies are `mcp` and
> `httpx`. It installs and runs in its own virtual environment and talks to the
> backend purely over HTTP, so it can be deployed independently — on the same
> machine, a sidecar container, or a remote host — by pointing it at a backend
> URL. The only runtime requirement is that the API is reachable and credentials
> are valid.

## Layout

```
mcp/
  bio_pipeline_mcp/
    __init__.py
    config.py       env-driven settings (+ .env loading)
    client.py       auth-aware httpx client (login, cookie jar, 401 re-auth)
    server.py       FastMCP server (stdio) — 71 tools grouped by subsystem
    http_server.py  streamable-HTTP transport + bearer auth (remote connector)
  pyproject.toml    installable package; scripts `bio-pipeline-mcp[-http]`
  requirements.txt  plain dependency list (mcp, httpx)
  .env.example      configuration template
  .gitignore        ignores .venv/, build artifacts, .env
  claude_desktop_config.example.json
  README.md         this file — setup & connect
  CLAUDE.md         operational guide an agent reads to drive the API
  .venv/            (gitignored) the server's own virtual environment
```

## Prerequisites

- The backend API must be running and reachable (dev: `http://127.0.0.1:8006`).
  See the repo root [CLAUDE.md](../CLAUDE.md) for how to start it.
- A user account on the backend. Bootstrap an admin if needed:
  `bio-pipeline auth bootstrap-admin --username admin`.

## Install

Give it its own virtual environment so it stays independently deployable:

```powershell
# from the repo root — only the path to mcp/ matters
python -m venv mcp/.venv
mcp/.venv/Scripts/python.exe -m pip install ./mcp     # add -e for an editable dev install
```

That pulls in `mcp` + `httpx` and drops a `bio-pipeline-mcp` console script into
`mcp/.venv/Scripts/`. Alternatives: `pipx install ./mcp` (isolated, on PATH) or
`uv pip install ./mcp`. You *can* reuse the project venv with
`./.venv/Scripts/python.exe -m pip install -e ./mcp` for quick local use, but a
dedicated venv is what keeps the server decoupled from the backend install.

## Configure

Copy `.env.example` → `.env` and fill in the base URL and credentials, **or**
pass them via the `env` block of the Claude Desktop config (recommended — keeps
secrets out of the repo). Variables:

| Variable | Default | Meaning |
|---|---|---|
| `BIO_PIPELINE_BASE_URL` | `http://127.0.0.1:8006` | Backend origin |
| `BIO_PIPELINE_API_PREFIX` | `/api/v1` | API route prefix |
| `BIO_PIPELINE_USERNAME` | — | Login username |
| `BIO_PIPELINE_PASSWORD` | — | Login password |
| `BIO_PIPELINE_TIMEOUT` | `60` | Per-request timeout (s) |
| `BIO_PIPELINE_VERIFY_TLS` | `true` | Verify TLS certs |

## Run

Once installed, run the console script (stdio transport — what Claude Desktop
launches). No `cwd` or `PYTHONPATH` needed:

```powershell
mcp/.venv/Scripts/bio-pipeline-mcp.exe
# equivalently:
mcp/.venv/Scripts/python.exe -m bio_pipeline_mcp.server
```

## Connect from Claude Desktop

Edit `claude_desktop_config.json` (Settings → Developer → Edit Config) and add
the server. A ready-to-edit example is in
[`claude_desktop_config.example.json`](claude_desktop_config.example.json):

```json
{
  "mcpServers": {
    "bio-pipeline-manager": {
      "command": "C:\\Users\\rh2310\\projects\\bioPipeline\\mcp\\.venv\\Scripts\\bio-pipeline-mcp.exe",
      "env": {
        "BIO_PIPELINE_BASE_URL": "http://127.0.0.1:8006",
        "BIO_PIPELINE_USERNAME": "admin",
        "BIO_PIPELINE_PASSWORD": "your-password"
      }
    }
  }
}
```

(Point `command` at the console script in whichever environment you installed
into — `mcp/.venv`, a `pipx` venv, etc. The script is self-contained, so no
`args`/`cwd` are required.)

Restart Claude Desktop; the `bio-pipeline-manager` tools appear in the 🔌 menu.

## Run as a remote connector (Cowork / claude.ai)

> **Why a different command:** Cowork and claude.ai run in the cloud, so they
> can't launch a local subprocess — they only reach **remote** MCP connectors
> over the network. Same MCP protocol, same 71 tools; only the *transport*
> changes from stdio to **streamable HTTP**.

The `bio-pipeline-mcp-http` entry point serves the same server over HTTP with a
shared-secret bearer-token guard. Configure it with the `BIO_PIPELINE_MCP_*`
vars (see `.env.example`):

```powershell
# generate a token once
$env:BIO_PIPELINE_MCP_AUTH_TOKEN = (python -c "import secrets;print(secrets.token_urlsafe(32))")
$env:BIO_PIPELINE_USERNAME = "admin"; $env:BIO_PIPELINE_PASSWORD = "your-password"
mcp/.venv/Scripts/bio-pipeline-mcp-http.exe       # serves http://127.0.0.1:8765/mcp
```

By default it binds loopback. To accept remote traffic you **must** set
`BIO_PIPELINE_MCP_AUTH_TOKEN` (it refuses to bind a non-loopback host without
one). Liveness probe: `GET /healthz` (unauthenticated).

**Expose it + register the connector:**

1. Put a public **HTTPS** URL in front of it — a tunnel (`cloudflared tunnel
   --url http://127.0.0.1:8765`, `ngrok http 8765`) or a reverse proxy with TLS.
   The endpoint is `https://<your-host>/mcp`.
2. In Claude → **Settings → Connectors → Add custom connector**, enter that URL.
3. Provide the bearer token as the connector's auth header
   (`Authorization: Bearer <token>`).

> ⚠️ Never expose the HTTP transport without both a token **and** TLS — it is a
> fully-authenticated gateway to the backend. The bearer guard is a pragmatic
> shared-secret scheme; for org use, front it with an OAuth-capable proxy. Exact
> connector-auth options follow Claude's current UI — see
> [custom connectors via remote MCP](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).

Per-conversation scoping (toggling the connector on only when relevant) works the
same as in Desktop — see the connectors menu.

## Tool catalog

Run `bio-pipeline-mcp` and inspect via any MCP client, or read
[CLAUDE.md](CLAUDE.md) for the grouped catalog and end-to-end workflows. There is
also a generic `api_request(method, path, params, body)` escape hatch for any
endpoint without a dedicated tool.

## Safety

- Tools that **write or run** (`submit_*`, `run_*`, `create_*`, `delete_*`,
  `publish_*`, `install_package`, …) act on real backend state. The agent should
  confirm destructive actions with the user.
- Credentials live only in the environment; they are never returned by any tool.
- Role is enforced server-side — a researcher account simply gets 403 on admin
  tools, surfaced as a clear error.
