# Project Overview

Last updated: 2026-06-15

This is the living map for Bio Pipeline Manager. Update it whenever a feature
changes project boundaries, runtime flow, public API, storage layout, or the
main UI workflows. For a quick orientation/navigation map, see the root
`CLAUDE.md`.

## What This Project Is

Bio Pipeline Manager is a local-first manager for YAML-defined bioinformatics
pipelines. It lets admins author and validate pipeline YAML, store reusable YAML
files, submit one-off pipeline tasks, define multi-stage/multi-task jobs, run
queued work locally, inspect logs, and manage the Python packages that provide
pipeline process functions.

On top of that authoring surface sit two newer workflows:

- **Publishing.** An admin turns a Job Definition into a **Published Job** with a
  small set of typed input fields, so non-author **researchers** can run it from a
  catalog — uploading or picking inputs, downloading output artifacts, and
  scheduling repeats. See `PublishedJob` / run workspaces below and
  `docs/TYPED_DEFINITIONS.md`.
- **AI Designer.** An admin-only chat (`/ai-chat`) that uses provider tools to
  inspect existing YAML, draft pipeline/Job Definition YAML, validate, and
  preview. It does **not** publish jobs.

The manager owns orchestration and the project-native pipeline engine in
`src/pipeline`. Scientific process functions remain external and are imported at
runtime from packages named in YAML, commonly `labUtils.*`.

## Architecture

```text
frontend/                      Next.js + TypeScript UI
backend/                       FastAPI HTTP API
src/bio_pipeline_manager/      Shared Python domain/service layer
src/pipeline/                  YAML pipeline engine and project helper processes
configs/app_config.yaml        Shared frontend/backend configuration
.bio_pipeline/                 Default local runtime state, ignored as app data
tests/                         Shared package unit/e2e tests
backend/tests/                 Backend API/config tests
frontend/src/**/*.test.ts[x]    Frontend unit tests
```

The key boundary is that FastAPI and the CLI should stay thin. Core behavior
belongs in `src/bio_pipeline_manager`, so the backend, CLI, notebook client, and
tests all exercise the same implementation.

## Runtime State

The default runtime home is `.bio_pipeline`, configured by
`backend.shared.pipeline_home` in `configs/app_config.yaml` and overrideable via
environment settings.

```text
.bio_pipeline/
  yamls/              Stored pipeline YAML files
  job_defs/           Active reusable Job Definition YAML files
  job_defs_archive/   Archived Job Definitions
  runs/               Per-published-run workspaces (inputs/, outputs/, artifact.zip, manifest.json)
  logs/               Per-task logs and generated task JSON files
  type_library.yaml   Project type library (named types for structured fields)
  state.sqlite        Jobs, tasks, groups, materialized stages, published jobs,
                      published runs, recurring schedules + recurring jobs, saved typed values
  installs.sqlite     Package install/uninstall audit log
  auth.sqlite         User and opaque session auth state
```

`YamlStore`, `JobDefinitionStore`, `RunWorkspaceStore`, and `SharedStorage` all
enforce that caller-supplied paths stay inside their roots (containment checks);
reuse that idiom for any new path input. Pipeline YAML files are validated before
saving; Job Definition files are structurally parsed before saving; the type
library is validated as a whole on every write.

## Main Concepts

Pipeline YAML is the lower-level executable pipeline format. It declares pipeline
inputs, processes, and outputs. The project-native engine builds these into a
callable process graph.

A Task is one concrete pipeline invocation. It has a pipeline YAML path, pipeline
name, output directory, input source overrides, optional `process_arg_mapping`,
status, log file, and scheduling metadata.

A Job Definition is a declarative YAML file that expands into many Tasks. It can
define a variable matrix, defaults, ordered stages, per-stage fan-out, stage
dependencies via `needs`, and templated values. See `docs/JOBS.md` for the full
schema and examples.

A Job Group is the submitted instance of a Job Definition. It stores the original
definition text and aggregates all child Task statuses into a rollup.

A Published Job is an admin-curated, researcher-facing wrapper around a Job
Definition. It exposes a small set of **typed input fields** (string, enum, file,
directory, glob, `typed`, …) and has a draft → published → archived lifecycle.
Researchers run it from a catalog; a run resolves field values to concrete paths,
renders the underlying Job Definition, and queues it. See
`src/bio_pipeline_manager/published_jobs.py`.

A Run Workspace is the isolated `runs/<id>/{inputs,outputs}` tree for one
published run. Researchers upload inputs (or reference an allowlisted shared
root) into it; the job writes outputs there; the reaper later zips outputs to
`artifact.zip` and TTL-cleans the workspace.

A Recurring Schedule replays a published run on a fixed interval (cloning the
originally-uploaded inputs each occurrence). The admin counterpart, a Recurring
Job, replays a single submitted job payload. Both share the same interval/end-rule
helpers and are fired by background `RecurringScheduler`s.

The Type Library is a project-level registry of named structured types (one
`type_library.yaml`). A published field can bind to a named type so researchers
edit a structured value (single / list / map) instead of raw JSON. Resolved
schemas are denormalized onto the field, so run time never needs the library.
Researchers can save and reuse field values (Saved Typed Values), keyed by
type rather than by job. See `docs/TYPED_DEFINITIONS.md`.

Users authenticate with username/password login and opaque server-side sessions.
There are two roles: `admin` and `user` (labelled "Researcher" in the UI). Admins
have access to all authoring/publishing workflows. Researchers get the
published-job catalog: browse Published Jobs, run them, track My Runs (download
artifacts, cancel, rewind), manage their schedules, and manage Saved Values.

## Execution Flow

One-off task submission:

```text
UI / CLI / client
  -> POST /api/v1/jobs or bio-pipeline submit
  -> JobQueue.submit()
  -> JobStore.create_job()
  -> queued Task row in state.sqlite
```

Running queued tasks:

```text
JobWorker or POST /api/v1/jobs/run-due or bio-pipeline run-due
  -> JobQueue.run_due()
  -> JobStore.list_due_jobs()
  -> JobStore.claim_job() atomically flips queued -> running
  -> LocalSubprocessRunner.run()
  -> python -m bio_pipeline_manager.run_task TASK.json
  -> pipeline.engine.build_pipeline_from_yaml(...)
  -> imported process functions execute
  -> JobStore.update_status()
```

The runner writes a `.task.json` file next to each log. The subprocess runs the
manager's own `bio_pipeline_manager.run_task` module rather than the old
`labUtils.scripts.run_a_pipeline` CLI, because this project needs to pass
`process_arg_mapping` into the pipeline builder.

Job Definition submission:

```text
JobDefinitionPanel / CLI job submit
  -> parse_job_definition()
  -> JobQueue.submit_definition()
  -> JobStore.create_group()
  -> materialize immediately eligible stages
  -> downstream stages materialize lazily inside run_due()
```

Lazy materialization matters for stages whose fan-out source is produced by an
upstream stage. First stages with missing fan-out inputs fail at submit/preview;
dependent stages can show as deferred in preview and materialize after upstream
success.

Published-job run (researcher-initiated or scheduler-fired):

```text
Catalog run / RecurringScheduler
  -> execute_published_run()              (published_runs.py — one shared path)
  -> resolve_io()                         field values -> concrete workspace/shared paths
  -> render_definition()                  -> concrete Job Definition text
  -> JobQueue.submit_definition()         -> Job Group + tasks (as above)
  -> PublishedRunRecord recorded
  ...task group runs via run_due...
  -> RunReaper: zip outputs to artifact.zip, deliver to shares, delete inputs,
     TTL-clean the workspace
```

Both the interactive submit endpoint and the recurring scheduler funnel through
`execute_published_run`, so a run is materialized identically whether a researcher
clicked Execute or a schedule fired it.

## Important Python Modules

`src/bio_pipeline_manager/models.py`
: Dataclasses and status enum for `JobSpec`, `JobRecord`, and job statuses.

`src/bio_pipeline_manager/storage.py`
: SQLite-backed `JobStore`. Owns job rows, job groups, materialized stage
tracking, atomic claiming, cancellation state, rollups, and migrations.

`src/bio_pipeline_manager/job_queue.py`
: Queue facade over `JobStore` and `LocalSubprocessRunner`. Handles submit,
Job Definition submission, lazy materialization, dependency readiness, blocking,
parallel `run_due`, cancellation, deletion, rewind, and group rollups.

`src/bio_pipeline_manager/runner.py`
: Local subprocess backend. Serializes a task file, sets `PYTHONPATH` so
`src/` imports work, records PID, captures stdout/stderr into the log, and maps
process return codes to final status.

`src/bio_pipeline_manager/run_task.py`
: Subprocess entry point for a single Task. Calls `build_pipeline_from_yaml` and
executes the resulting pipeline.

`src/bio_pipeline_manager/job_definition.py`
: Parser and expander for multi-task Job Definition YAML. Implements variable
matrix expansion, templating, fan-out (`none`, `mapping_file`, `patterns`,
`folders`), dependency validation, deferred preview, and materialized tasks.

`src/bio_pipeline_manager/yaml_store.py`
: Filesystem CRUD for pipeline YAML files plus validation and pipeline-name
inspection.

`src/bio_pipeline_manager/job_definition_store.py`
: Filesystem CRUD for reusable Job Definition YAML files, including folder
operations and archive/restore support.

`src/bio_pipeline_manager/yaml_validation.py`
: Schema-aware inspection of labUtils-style YAML. Optional import validation can
check that packages and methods resolve.

`src/bio_pipeline_manager/packages.py`
: Package listing and install/uninstall into the same Python interpreter used by
the backend and runner. Writes an audit trail and refuses mutations while jobs
are running.

`src/bio_pipeline_manager/worker.py`
: Background polling worker started by FastAPI lifespan when enabled. Calls
`queue.run_due()` at the configured interval.

`src/bio_pipeline_manager/cli.py`
: `bio-pipeline` command surface for init, YAML CRUD/validation, templates,
single-task submission, job definitions, queue execution, cancellation, and
environment package operations.

`src/bio_pipeline_manager/client.py`
: Lightweight HTTP client intended for notebooks/scripts.

`src/bio_pipeline_manager/auth_models.py`
: User/session dataclasses and role enum.

`src/bio_pipeline_manager/auth_store.py`
: SQLite-backed user and session persistence.

`src/bio_pipeline_manager/auth_service.py`
: Password hashing, login verification, session creation/revocation, current
user lookup, and first-admin bootstrap.

`src/bio_pipeline_manager/published_jobs.py`
: `PublishedJobStore` plus the published-field type set, `resolve_io` (field
values → concrete paths), and `render_definition`. Owns the draft/published/
archived lifecycle and run records in `state.sqlite`.

`src/bio_pipeline_manager/published_runs.py`
: The single shared execution path (`execute_published_run`) used by both the
interactive submit endpoint and the recurring scheduler, so manual and scheduled
runs never drift.

`src/bio_pipeline_manager/run_workspace.py`
: `RunWorkspaceStore` — per-run `inputs/outputs` trees with a manifest, upload
quota, and path-containment checks. Never exposes the server filesystem.

`src/bio_pipeline_manager/run_reaper.py`
: Background delivery + cleanup for finished runs: zips outputs to `artifact.zip`,
copies shared-delivery outputs to an allowlisted share, deletes inputs, and
TTL-removes workspaces. Runs alongside `JobWorker`.

`src/bio_pipeline_manager/shared_storage.py`
: `SharedStorage` — allowlisted, config-backed shared roots a researcher may
browse/pick instead of uploading; every sub-path is containment-checked.

`src/bio_pipeline_manager/recurring_schedule.py`
: `RecurringScheduleStore` + `RecurringScheduler` for repeating a published run
(clones inputs each occurrence). Holds interval/end-rule helpers (`advance`,
`interval_delta`, `END_MODES`).

`src/bio_pipeline_manager/recurring_job.py`
: Admin counterpart — repeats a single submitted job payload, reusing the
schedule helpers above.

`src/bio_pipeline_manager/type_schema.py`
: Named-type schema engine: `validate_library`, `resolve_type` (flatten to a
self-contained `type_schema`), and `coerce_typed_value` (fail-closed validation).

`src/bio_pipeline_manager/type_library_store.py`
: `TypeLibraryStore` — the project type library persisted as one YAML file,
validated as a whole on every write.

`src/bio_pipeline_manager/type_extract.py`
: Introspects a Python class (TypedDict / dataclass / Pydantic) into type-library
entries; surfaced on the Environment page.

`src/bio_pipeline_manager/typed_value_store.py`
: `SavedTypedValueStore` — per-researcher reusable values for typed fields, keyed
by `(user_id, type_key, container)` rather than by job.

`src/bio_pipeline_manager/backup.py`
: `build_backup` / `import_backup` — bundle pipelines, Job Definitions, published
jobs, the type library, and a generated `requirements.txt` of the extra packages
(reconstructed from the install audit log) into a portable zip, and apply such a zip
on another server. Import is per-item overwrite-or-skip and (optionally) feeds the
requirements file through `PackageManager.install` so imported work is runnable.
Runs, queues, logs, and users are never part of a backup.

`src/bio_pipeline_manager/ai_agent.py`
: AI Designer orchestrator (system prompt + tool loop). Pairs with
`ai_providers.py` (Claude/OpenAI/Gemini/OpenAI-compatible adapters),
`ai_tools.py` (allowlisted, Pydantic-validated tools over existing stores), and
`ai_schema_provider.py` (dynamic schema bundle injected into the prompt).

## Pipeline Engine

`src/pipeline/engine.py` contains the project-native process/YAML engine. It
imports each process by `package` and `method`, supports input/process/output
construction, process chaining/forking/joining, cached inputs, and per-process
parameter overrides.

`src/pipeline/io.py` contains mapping and filesystem helpers used by both the
engine and Job Definition fan-out.

`src/pipeline/helpers/` contains project-local reusable process functions that
can be referenced from YAML as:

```yaml
package: pipeline.helpers
method: function_name
```

## Backend API

FastAPI is assembled in `backend/app/main.py`. It registers routers under
`settings.api_prefix`, currently `/api/v1`.

```text
GET  /health                       Unauthenticated liveness

# Admin-only (mounted with ADMIN_ONLY, or via their own require_admin)
/api/v1/ai-chat                    AI Designer: context, schema, test-provider, messages
/api/v1/runtime                    Runtime paths and current environment info
/api/v1/pipeline-yamls             Pipeline YAML tree, CRUD, folders, move
/api/v1/validation                 Validate raw or stored pipeline YAML
/api/v1/templates                  Built-in starter pipeline YAML templates
/api/v1/jobs                       One-off task queue, logs, cancel, delete, rewind, run-due
/api/v1/job-definitions            Preview, submit, list, and inspect Job Groups
/api/v1/job-definition-store       Saved Job Definition tree, CRUD, archive, restore
/api/v1/job-definition-templates   Built-in starter Job Definition templates
/api/v1/packages                   Package list/install/uninstall (admin)
/api/v1/backup                     Export a project backup zip / import one (admin)
/api/v1/type-library               Project type library CRUD + Python-class extraction (admin)
/api/v1/users                      User (researcher) management (admin)

# Per-endpoint auth (router mounted without ADMIN_ONLY)
/api/v1/auth                       Login (public), logout, current-user, change-password
/api/v1/published-jobs/admin/*     Admin: inspect, create, edit, publish, archive, validate, preview
/api/v1/published-jobs (+/catalog/*, /my-runs/*, /my-schedules/*)
                                   Researcher: browse catalog, browse shared roots, upload,
                                   run, track runs (artifact/cancel/rewind/delete), schedules
/api/v1/saved-typed-values         Researcher: reusable saved values for typed fields
```

Auth boundary: every route except `/health` and `/auth/login` requires an
authenticated session. Most are **admin-only** — either mounted with the shared
`ADMIN_ONLY` dependency in `main.py`, or carrying their own
`dependencies=[Depends(require_admin)]` (e.g. `packages`, `type-library`,
`users`). The **researcher-reachable** surface self-gates per endpoint with
`require_authenticated_user`: `published-jobs` catalog/`my-runs`/`my-schedules`
and `saved-typed-values` (and `auth` me/logout/change-password). The
`published-jobs` router mixes both — its `/admin/*` paths require admin.

Runtime wiring is centralized in `backend/app/services/runtime.py`, which
constructs one frozen `PipelineRuntime` from the configured home path:

```text
YamlStore               JobStore               JobQueue
PackageManager          JobDefinitionStore     PublishedJobStore
RecurringScheduleStore  RecurringJobStore      RunWorkspaceStore
SharedStorage           TypeLibraryStore       SavedTypedValueStore
AuthService
```

`backend/app/main.py` also starts background loops in the API lifespan when
enabled: `JobWorker` (run-due), `RunReaper` (output delivery + TTL cleanup), and
two `RecurringScheduler`s (published schedules + admin recurring jobs).

Configuration is loaded from `configs/app_config.yaml`, merged by active
environment. Selection priority is `APP_ENV`, then `defaults.environment`.
`APP_CONFIG_PATH` can point at another config file. Pydantic settings can also
read `.env` files at repo and backend level.

## Frontend

The frontend is a Next.js App Router application on port `3005` in development.
The typed API client is `frontend/src/lib/api.ts`; shared types are
`frontend/src/types/index.ts`.

`frontend/src/components/pipelines/AppShell.tsx` owns the common header,
navigation, and status bar — and renders **two nav sets** by role (full admin nav
vs. the researcher's catalog nav). `AuthContext.tsx` + `AuthGate.tsx` are the auth
shell above it. `PipelineContext.tsx` stores cross-page UI state for the currently
selected pipeline YAML and pending Job Definition drafts.

Unauthenticated visitors see the login page. Admins see the full app; researchers
see only their catalog pages. (`/under-construction` still exists as a fallback
landing page but is no longer the researcher destination.)

Admin pages and primary panels:

```text
/                       JobQueuePanel          List/run/cancel/delete/rewind tasks, view logs ("Job Queue")
/ai-chat                AI Designer            Admin AI chat for drafting/validating YAML
/published-jobs-admin   (Job Publishing)       Create/edit/publish/archive Published Jobs
/job-definitions        JobDefinitionPanel     Author, preview, submit, monitor Job Definitions
/job-storage            JobStoragePanel        Save/open/archive/restore reusable Job Definitions
/submit                 SubmitPanel            Submit one pipeline from stored YAML ("Pipeline Submit")
/validation             ValidationPanel        Edit/validate/template/save pipeline YAML ("Pipeline Definitions")
/storage                YamlStoragePanel        Browse/create/move/delete stored pipeline YAML ("Pipeline Storage")
/environment            EnvironmentPanel       Packages + TypeLibraryPanel (type library & extraction)
/backup                 BackupPanel            Export a project backup zip / import one ("Backup")
/users                  UserManagementPanel    Manage researchers ("Researchers")
/change-password        Change password
```

Researcher pages:

```text
/published-jobs         Browse the published-job catalog and run jobs
/my-runs                Track own runs: status, logs, artifact download, cancel, rewind
/saved-values           Manage reusable Saved Typed Values (TypedValueEditor)
/change-password        Change password
/login                  Login page
```

Graph helpers live in `frontend/src/lib/pipelineGraph.ts` and
`frontend/src/lib/jobStageGraph.ts`. Draft and config helpers live in
`frontend/src/lib/pipelineDraft.ts` and `frontend/src/lib/projectConfig.ts`.
Frontend tests are co-located Vitest files (`*.test.ts[x]`).

## Existing Docs

`docs/JOBS.md`
: Practical Job Definition reference. Update when schema, fan-out, templating,
dependency semantics, CLI, API, or UI behavior changes.

`docs/JOBS_REDESIGN.md`
: Design rationale and rollout history for multi-task jobs.

`docs/TYPED_DEFINITIONS.md`
: Type library and structured ("typed") published-job fields — containers,
extraction from Python classes, coercion rules.

`docs/AUTH_ARCHITECTURE_PLAN.md`
: Migration from the local package admin token to real users, login, server-side
sessions, admin/user roles, and admin user management.

`docs/AI_PIPELINE_DESIGNER_CONTEXT.md`
: Live system-prompt context loaded by the AI Designer backend.

`docs/ai_agent.md`
: Original AI-chat design plan. Partly superseded: the AI Designer does **not**
create or publish Published Jobs.

`docs/components.md`
: Older component/layer summary. This overview should be treated as the fresher
map if the two disagree.

Root `CLAUDE.md`
: Concise orientation/navigation map for AI agents (subsystem→code table, auth
model, dev/test commands, gotchas). Points back here for detail.

## Development Commands

Python setup:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,api]"
```

Install local `labUtils` for co-development when needed:

```bash
python -m pip install -e "/Users/roozbeh/Research/Geoff Lab/projects/lab_utils/src"
```

Run backend:

```bash
uvicorn app.main:app --app-dir backend --reload --reload-dir backend --reload-dir src --port 8006
```

Port 8006 is the dev backend port the frontend proxies `/api/v1` to (see
`configs/app_config.yaml` `frontend.development.api_url`). `--reload-dir backend
--reload-dir src` scopes the auto-reloader to the source trees only. Without it
the reloader watches `.venv` too, so a package install from the Environment page
restarts the worker mid-install. On Windows the venv interpreter is
`./.venv/Scripts/python.exe`.

Run frontend:

```bash
cd frontend
npm install
npm run dev
```

Run tests:

```bash
pytest
cd frontend
npm run type-check
npm test
```

Useful CLI examples:

```bash
bio-pipeline init
bio-pipeline yaml list
bio-pipeline yaml validate growth.yaml
bio-pipeline submit growth.yaml pipeline_name --output-dir ./outputs/run-001
bio-pipeline job preview definition.yaml
bio-pipeline job submit definition.yaml
bio-pipeline run-due --parallel 2
bio-pipeline jobs
bio-pipeline auth bootstrap-admin --username admin
```

## When Adding Features

Update this file when a feature changes any of these:

- Repository structure or ownership boundaries.
- Runtime state under `.bio_pipeline`.
- Queue, runner, worker, or Job Definition lifecycle.
- Public API route shape.
- Main frontend pages, panels, or cross-page state.
- Configuration keys or environment variables.
- Developer commands or test strategy.

Also update the focused docs when relevant:

- Job Definition schema/behavior: `docs/JOBS.md`.
- UI/component responsibilities: `docs/components.md`.
- README-level setup or user-facing quickstart: `README.md`.

Implementation checklist by feature type:

- New backend capability: put core behavior in `src/bio_pipeline_manager`,
  expose it through `backend/app/api/routes`, add/adjust schemas in
  `backend/app/schemas`, and cover both service and route tests.
- New frontend workflow: add typed API functions in `frontend/src/lib/api.ts`,
  shared types in `frontend/src/types/index.ts`, page/panel wiring under
  `frontend/src/app` and `frontend/src/components/pipelines`, plus focused
  Vitest coverage for non-trivial state or graph logic.
- New runtime persistence: document the file/table in this overview, add
  migrations or path-safety checks if needed, and include tests for existing
  state compatibility.
- New queue behavior: test the `JobStore`/`JobQueue` path first, then the API
  and UI path. Be careful with atomic claiming, dependency statuses, and
  cancellation races.
- New package/import behavior: remember that tasks run in a subprocess using the
  backend interpreter. Package operations must stay guarded while jobs run.
- New researcher-facing capability: gate the route with
  `require_authenticated_user` (not `require_admin`), keep it inside the
  `published-jobs` catalog / `saved-typed-values` surface, and add it to the
  researcher nav set in `AppShell.tsx`. Never expose admin authoring routes to
  researchers.
- New published-job / typed-field behavior: core logic in `published_jobs.py` /
  `type_schema.py`; keep the manual and scheduled run paths funnelling through
  `execute_published_run`; update `docs/TYPED_DEFINITIONS.md`.
- New auth/role behavior: there are now two roles (`admin`, `user`). Keep admin
  authoring/publishing routes admin-only; researcher routes self-gate per
  endpoint. Update `docs/AUTH_ARCHITECTURE_PLAN.md` and this overview together.
