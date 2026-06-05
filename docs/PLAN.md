# Initial Project Plan

## Goal

Create a lightweight manager around the existing `labUtils` YAML pipeline execution
system. The manager should help users create, edit, store, queue, schedule, execute,
inspect, and debug pipeline jobs without changing the `labUtils` engine.

## Architecture

```text
Notebook / Browser / CLI
        |
        v
Manager API and CLI
        |
        +-- YAML store
        +-- SQLite job store
        +-- Queue / scheduler
        +-- Log store
        |
        v
Execution backend
        |
        +-- local subprocess: python -m labUtils.scripts.run_a_pipeline ...
        +-- future Docker backend
        |
        v
External labUtils package
```

## Phase 1: Skeleton

- Create Python package structure.
- Add YAML store with validation and path-safety checks.
- Add SQLite job store with statuses and log paths.
- Add local subprocess runner that captures stdout/stderr.
- Add queue runner for due jobs with parallel workers.
- Add CLI commands for initialization, YAML save/list/show, submit, run-due, and jobs.
- Add FastAPI app factory with basic endpoints.
- Add unit and e2e tests.

## Phase 2: YAML Authoring

- Add schema-aware YAML editing helpers.
- Inspect importable package methods and signatures.
- Add pipeline templates.
- Add validation that checks:
  - pipeline names
  - required sections
  - importable packages
  - callable methods
  - parameter references to previous payload names

## Phase 3: UI

- Start with FastAPI plus a simple browser UI.
- Use CodeMirror or Monaco for YAML editing.
- Show:
  - YAML files
  - pipeline names
  - submit form
  - queue table
  - job status
  - live logs

## Phase 4: Jupyter Client

- Add a small Python client for notebooks.
- Add optional widgets for:
  - YAML selection
  - input overrides
  - submit and watch
  - logs

Jupyter should remain a client, not the queue engine.

## Phase 5: Backends

- Keep local subprocess as the default backend.
- Add Docker backend with mounted YAML, input, output, and log directories.
- Add cancellation support.
- Add resource limits where possible.

## Current Assumptions

- `labUtils` is installed separately in the active environment.
- Pipeline execution is best isolated in a subprocess.
- SQLite is sufficient for initial state.
- Filesystem storage is sufficient for YAML files, logs, and output artifacts.

