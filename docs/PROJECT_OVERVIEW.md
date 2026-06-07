# Project Overview

Last updated: 2026-06-07

This is the living map for Bio Pipeline Manager. Update it whenever a feature
changes project boundaries, runtime flow, public API, storage layout, or the
main UI workflows.

## What This Project Is

Bio Pipeline Manager is a local-first manager for YAML-defined bioinformatics
pipelines. It lets users author and validate pipeline YAML, store reusable YAML
files, submit one-off pipeline tasks, define multi-stage/multi-task jobs, run
queued work locally, inspect logs, and manage the Python packages that provide
pipeline process functions.

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
  logs/               Per-task logs and generated task JSON files
  state.sqlite        Job, task, group, and materialized-stage state
  installs.sqlite     Package install/uninstall audit log
  auth.sqlite         User and opaque session auth state
```

`YamlStore` and `JobDefinitionStore` both enforce relative paths that stay inside
their store roots. Pipeline YAML files are validated before saving. Job
Definition files are structurally parsed before saving.

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

Users authenticate with username/password login and opaque server-side sessions.
There are two roles: `admin` and `user`. Admins have access to all current
workflows. Ordinary users can log in but currently land on an
under-construction page until user-specific workflows are designed.

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
GET  /health

/api/v1/runtime                    Runtime paths and current environment info
/api/v1/pipeline-yamls             Pipeline YAML tree, CRUD, folders, move
/api/v1/validation                 Validate raw or stored pipeline YAML
/api/v1/templates                  Built-in starter pipeline YAML templates
/api/v1/jobs                       One-off task queue, logs, cancel, delete, rewind, run-due
/api/v1/job-definitions            Preview, submit, list, and inspect Job Groups
/api/v1/job-definition-store       Saved Job Definition tree, CRUD, archive, restore
/api/v1/job-definition-templates   Built-in starter Job Definition templates
/api/v1/packages                   Package list/install/uninstall for signed-in admins
/api/v1/auth                       Login, logout, current user session
/api/v1/users                      Admin-only user management
```

All current application routes above require an authenticated `admin` user,
except `/health` and login/logout/current-user routes. `/api/v1/packages` uses
the same admin session/role check as the rest of the admin API.

Runtime wiring is centralized in `backend/app/services/runtime.py`, which
constructs one `PipelineRuntime` from the configured home path:

```text
YamlStore
JobStore
JobQueue
PackageManager
JobDefinitionStore
```

Configuration is loaded from `configs/app_config.yaml`, merged by active
environment. Selection priority is `APP_ENV`, then `defaults.environment`.
`APP_CONFIG_PATH` can point at another config file. Pydantic settings can also
read `.env` files at repo and backend level.

## Frontend

The frontend is a Next.js App Router application on port `3005` in development.
The typed API client is `frontend/src/lib/api.ts`; shared types are
`frontend/src/types/index.ts`.

`frontend/src/components/pipelines/AppShell.tsx` owns the common header,
navigation, and status bar. `PipelineContext.tsx` stores cross-page UI state for
the currently selected pipeline YAML and pending Job Definition drafts.

An auth shell sits above `AppShell`. Unauthenticated visitors see the login
page. Authenticated admins see the existing admin app and the user-management
page. Authenticated ordinary users go to an under-construction page for now.

Pages and primary panels:

```text
/                  JobQueuePanel        List/run/cancel/delete/rewind tasks and view logs
/job-definitions   JobDefinitionPanel   Author, preview, submit, and monitor Job Definitions
/job-storage       JobStoragePanel      Save/open/archive/restore reusable Job Definitions
/submit            SubmitPanel          Submit one pipeline from stored YAML
/validation        ValidationPanel      Edit, validate, template, and save pipeline YAML
/storage           YamlStoragePanel     Browse/create/move/delete stored pipeline YAML
/environment       EnvironmentPanel     List/install/uninstall backend Python packages
/users             Admin user-management page
/login             Login page
/under-construction Ordinary-user landing page
```

Graph helpers live in `frontend/src/lib/pipelineGraph.ts` and
`frontend/src/lib/jobStageGraph.ts`. Draft and config helpers live in
`frontend/src/lib/pipelineDraft.ts` and `frontend/src/lib/projectConfig.ts`.

## Existing Docs

`docs/JOBS.md`
: Practical Job Definition reference. Update when schema, fan-out, templating,
dependency semantics, CLI, API, or UI behavior changes.

`docs/JOBS_REDESIGN.md`
: Design rationale and rollout history for multi-task jobs.

`docs/AUTH_ARCHITECTURE_PLAN.md`
: Migration from the local package admin token to real users, login, server-side
sessions, admin/user roles, and admin user management.

`docs/components.md`
: Older component/layer summary. This overview should be treated as the fresher
map if the two disagree.

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
uvicorn app.main:app --app-dir backend --reload --port 8005
```

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
- New auth/role behavior: keep all existing pages and APIs admin-only until
  user-specific workflows are explicitly designed. Update
  `docs/AUTH_ARCHITECTURE_PLAN.md` and this overview together.
