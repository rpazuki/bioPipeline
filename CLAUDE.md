# CLAUDE.md — Bio Pipeline Manager

Orientation map for AI agents. Read this first; it tells you *where to look*
rather than restating everything. The detailed living map is
[docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md).

> Last reviewed: 2026-06-15 (Opus). Keep this current when a feature changes a
> boundary, route, page, role, runtime-state file, or dev command.

## What this is

A **local-first manager for YAML-defined bioinformatics pipelines**. Admins
author/validate pipeline YAML, compose multi-stage **Job Definitions**, and
**publish** parameterised jobs; **researchers** (ordinary users) run those
published jobs from a catalog — uploading or picking inputs, downloading output
artifacts, and scheduling repeats. The scientific process functions are
**external** (`labUtils.*`), imported at runtime by name from YAML.

## The golden rule (architecture)

Three layers; the HTTP API and CLI stay **thin**. All real behavior lives in the
shared Python layer so backend, CLI, notebook client, and tests exercise the
same code.

```
frontend/                      Next.js + TS UI (App Router). Port 3005 in dev.
backend/                       FastAPI HTTP API (thin). Port 8006 in dev.
src/bio_pipeline_manager/      ← SHARED DOMAIN/SERVICE LAYER. Put logic HERE.
src/pipeline/                  Project-native YAML→process engine + helpers.
configs/app_config.yaml        Merged frontend+backend config (env profiles).
.bio_pipeline/                 Local runtime state (gitignored app data).
```

When adding a feature: core logic in `src/bio_pipeline_manager` → expose via a
route in `backend/app/api/routes` → schema in `backend/app/schemas` → typed
client fn in `frontend/src/lib/api.ts` → page/panel in `frontend/src`. Cover
**both** the service test (`tests/unit`) and the route test (`backend/tests`).

## Where things live (subsystem → code map)

| Subsystem | Domain module(s) `src/bio_pipeline_manager/` | Route `backend/app/api/routes/` (prefix under `/api/v1`) | Frontend page `frontend/src/app/` |
|---|---|---|---|
| Pipeline YAML store/validate | `yaml_store.py`, `yaml_validation.py` | `storage.py` (`/pipeline-yamls`), `validation.py` (`/validation`), `templates.py` (`/templates`) | `storage/` (Pipeline Storage), `validation/` (Pipeline Definitions) |
| Pipeline engine | `src/pipeline/engine.py`, `io.py`, `helpers/` | — | `PipelineBuilder.tsx`, `PipelineSchematic.tsx` |
| One-off tasks / queue | `models.py`, `storage.py` (`JobStore`), `job_queue.py`, `runner.py`, `run_task.py`, `worker.py` | `jobs.py` (`/jobs`) | `submit/`, `/` (Job Queue) |
| Job Definitions (multi-task) | `job_definition.py`, `job_definition_store.py`, `job_definition_templates.py` | `job_definitions.py`, `job_definition_store.py`, `job_definition_templates.py` | `job-definitions/`, `job-storage/` |
| **Published jobs** (researcher-facing) | `published_jobs.py`, `published_runs.py`, `run_workspace.py`, `run_reaper.py`, `shared_storage.py` | `published_jobs.py` (`/published-jobs`: `/admin/*` = admin, `/catalog/*` + `/my-runs/*` + `/my-schedules/*` = researcher) | `published-jobs-admin/` (admin), `published-jobs/` + `my-runs/` (researcher) |
| **Recurring schedules** | `recurring_schedule.py` (published runs), `recurring_job.py` (admin jobs) | within `published_jobs.py` + scheduler in `main.py` lifespan | scheduling UI inside the panels above |
| **Type library / typed fields** | `type_schema.py`, `type_library_store.py`, `type_extract.py`, `typed_value_store.py` | `type_library.py` (`/type-library`, admin), `saved_typed_values.py` (`/saved-typed-values`, researcher) | `TypeLibraryPanel.tsx` (on Environment), `TypedValueEditor.tsx`, `saved-values/` |
| **AI Designer** (admin chat) | `ai_agent.py`, `ai_providers.py`, `ai_tools.py`, `ai_schema_provider.py` | `ai_chat.py` (`/ai-chat`, admin) | `ai-chat/` |
| Packages / environment | `packages.py`, `package_introspect.py` (read-only: list/search installed functions+classes, get a signature) | `packages.py` (`/packages`, admin; `/packages/inspect` `/search` `/signature` = introspection) | `environment/` |
| **Backup / restore** | `backup.py` | `backup.py` (`/backup`, admin) | `backup/` |
| Auth & users | `auth_models.py`, `auth_store.py`, `auth_service.py` | `auth.py` (`/auth`), `users.py` (`/users`, admin) | `login/`, `users/` (Researchers), `change-password/` |
| CLI / notebook client | `cli.py`, `client.py` | — | — |

Runtime wiring hub: [`backend/app/services/runtime.py`](backend/app/services/runtime.py)
builds one frozen `PipelineRuntime` (all stores) from the home path.
Auth deps: [`backend/app/api/deps.py`](backend/app/api/deps.py) (`require_admin`,
`require_authenticated_user`, sliding session renewal). Router assembly +
background workers: [`backend/app/main.py`](backend/app/main.py).

## Roles & auth boundary

Username/password login → opaque server-side sessions (cookie). Two roles:

- **admin** ("Administrator"): full nav — AI Designer, Job Publishing, Job
  Queue, Job/Pipeline Definitions & Storage, Environment, Researchers.
- **user** ("Researcher"): catalog only — Published Jobs, My Runs, Saved Values,
  Change Password. (Earlier docs say researchers land on an under-construction
  page — that is **stale**; they now have the published-job workflow.)

Most routers are admin-only (mounted with `ADMIN_ONLY` in `main.py`, or via their
own `dependencies=[Depends(require_admin)]`). The researcher-reachable surface is
**`/published-jobs/catalog|my-runs|my-schedules`** and **`/saved-typed-values`**,
which self-gate per-endpoint with `require_authenticated_user`. `/auth/login` is
public; `/health` is unauthenticated.

## Runtime state (`.bio_pipeline/`)

```
yamls/            stored pipeline YAML        job_defs/ + job_defs_archive/  Job Definitions
runs/             per-published-run workspaces (inputs/outputs/artifact.zip)
logs/             per-task logs + generated .task.json
type_library.yaml project type library (one human-readable YAML file)
state.sqlite      jobs, groups, materialized stages, published jobs, recurring
                  schedules/jobs, saved typed values
installs.sqlite   package install/uninstall audit      auth.sqlite  users + sessions
```

Background loops (started in the API lifespan when `worker_enabled`):
`JobWorker` (runs due tasks), `RunReaper` (zips outputs, delivers to shares,
deletes inputs, TTL-cleans workspaces), and two `RecurringScheduler`s (published
schedules + admin recurring jobs).

## Dev & test commands (Windows / PowerShell)

- **venv interpreter:** `./.venv/Scripts/python.exe` — the bare `python` on PATH
  does **not** have `bio_pipeline_manager` installed.
- **Backend dev:** `uvicorn app.main:app --app-dir backend --reload --reload-dir backend --reload-dir src --port 8006`
  (`--reload-dir` scopes the reloader so a package install from the Environment
  page doesn't churn `.venv` and restart mid-install). Dev frontend proxies
  `/api/v1` → `http://localhost:8006`.
- **Frontend dev:** from `frontend/`, `npm run dev` (port 3005, defined in
  `.claude/launch.json`). Next 16 allows one dev instance per folder — stop a
  running one first.
- **Backend route tests:** run from `backend/`:
  `cd backend; ../.venv/Scripts/python.exe -m pytest -q`.
- **All tests:** `./.venv/Scripts/python.exe -m pytest -s` from repo root.
  `pyproject.toml` sets `pythonpath=['src','backend']`, `testpaths=['tests','backend/tests']`.
  **Quirk:** without `-s`, the top-level run crashes in capture teardown
  (`ValueError: I/O operation on closed file`) — exit code is still 0, not a real
  failure. `-s` avoids it.
- **Frontend checks:** from `frontend/`: `npx tsc --noEmit`, `npx eslint .`
  (the `react-hooks/set-state-in-effect` warnings on the fetch-in-`useEffect`
  pattern are warnings only), `npx vitest run`.
- **Local admin login** for driving authenticated flows: see personal memory
  (`running-tests.md`); bootstrap with `bio-pipeline auth bootstrap-admin --username admin`.

## CLI surface (`bio-pipeline`, entry point `cli:main`)

`init`, `yaml save|list|show|validate`, `template list|show`, `submit`,
`run-due`, `jobs`, `cancel`, `job preview|submit|status`, `env list|install|uninstall`,
`auth bootstrap-admin`. Published jobs, recurring schedules, type library, and
saved values are **API/UI-only** (no CLI yet).

## Gotchas

- **Two FastAPI apps exist.** The real one is `backend/app/main.py`. The minimal,
  auth-less `src/bio_pipeline_manager/api/app.py` (`create_app(home)`) is a legacy
  standalone used by the notebook client and `tests/unit/test_api_app.py` — don't
  confuse them.
- Tasks run as **subprocesses** (`python -m bio_pipeline_manager.run_task TASK.json`)
  using the backend's interpreter, so package operations are guarded while jobs run.
- Job Definition downstream stages **materialize lazily** inside `run_due` when
  their fan-out source is produced upstream — preview can show stages as deferred.
- **AI provider keys** come from `.env`/environment (`${VAR}` placeholders, or a
  conventional per-provider var like `ANTHROPIC_API_KEY`); never returned to the
  frontend, never logged. Config under `backend.shared.ai` in `app_config.yaml`.
- `YamlStore`, `JobDefinitionStore`, `RunWorkspaceStore`, and `SharedStorage` all
  containment-check caller paths — reuse that idiom for any new path input; never
  expose the server filesystem.

## MCP server (agent/LLM access)

[`mcp/`](mcp/) holds a **self-contained Model Context Protocol** server
(`bio-pipeline-manager`) that exposes the backend API as ~70 tools so an agent or
LLM — via **Claude Desktop** or **Cowork** — can do CRUD on and *run* pipelines,
jobs, job definitions, published jobs, runs, queues, schedules, the type library,
users, and packages. It shares **no code** with `backend/` or `src/` (deps: just
`mcp` + `httpx`); it is a thin, auth-aware `httpx` client over `/api/v1`
([`mcp/bio_pipeline_mcp/client.py`](mcp/bio_pipeline_mcp/client.py)) with its own
`pyproject.toml`, so it installs into its own venv and deploys independently of
the backend. Each tool maps to a route
([`mcp/bio_pipeline_mcp/server.py`](mcp/bio_pipeline_mcp/server.py)).

- **Auth:** logs in with `BIO_PIPELINE_USERNAME`/`PASSWORD` and reuses the session
  cookie; the account's **role** gates the surface (admin = everything,
  researcher = catalog/run/saved-values) — same roles as the HTTP API.
- **Run it:** install standalone (`python -m venv mcp/.venv;
  mcp/.venv/Scripts/python.exe -m pip install ./mcp`), start the backend (port
  8006), then run the `bio-pipeline-mcp` console script (stdio) — or wire it into
  Claude Desktop via
  [`mcp/claude_desktop_config.example.json`](mcp/claude_desktop_config.example.json).
- **Two transports, same tools:** `server.py` = stdio (local, Claude Desktop);
  [`http_server.py`](mcp/bio_pipeline_mcp/http_server.py) = streamable-HTTP with a
  bearer-token guard (`bio-pipeline-mcp-http`) for **remote connectors**
  (Cowork / claude.ai), since a cloud host can't spawn a local subprocess. Only
  the transport differs — the 71 tools are identical. See `mcp/README.md`.
- **Agent context:** [`mcp/CLAUDE.md`](mcp/CLAUDE.md) is the operational guide an
  agent reads to map user requests to tool calls; [`mcp/README.md`](mcp/README.md)
  is the human setup guide.
- **Keep it current:** when you add/rename/remove a route or change its
  request/response shape, update the matching tool in `server.py` and the catalog
  in `mcp/CLAUDE.md`. The MCP layer stays thin — no logic beyond request shaping.

## Doc index

| Doc | Read it for |
|---|---|
| [mcp/CLAUDE.md](mcp/CLAUDE.md) | Driving the system through the MCP server (tools, workflows, entity model). |
| [mcp/README.md](mcp/README.md) | Installing/connecting the MCP server (Claude Desktop / Cowork). |
| [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) | The detailed living map (modules, flows, API, pages). |
| [docs/JOBS.md](docs/JOBS.md) | Job Definition schema, fan-out, templating, dependencies. |
| [docs/JOBS_REDESIGN.md](docs/JOBS_REDESIGN.md) | Why multi-task jobs work the way they do. |
| [docs/TYPED_DEFINITIONS.md](docs/TYPED_DEFINITIONS.md) | Type library + structured published-job fields. |
| [docs/AUTH_ARCHITECTURE_PLAN.md](docs/AUTH_ARCHITECTURE_PLAN.md) | Users, login, sessions, roles. |
| [docs/AI_PIPELINE_DESIGNER_CONTEXT.md](docs/AI_PIPELINE_DESIGNER_CONTEXT.md) | Live system-prompt context for the in-app AI Designer. |
| [docs/ai_agent.md](docs/ai_agent.md) | Original AI-chat design plan (partly superseded: AI does **not** publish jobs). |
| [docs/components.md](docs/components.md) | Older component/layer summary (PROJECT_OVERVIEW wins on conflict). |
| [README.md](README.md) | Setup, install, user-facing quickstart. |
