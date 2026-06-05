# Components

This project is split into three layers:

```text
frontend/                 Next.js + TypeScript user interface
backend/                  FastAPI HTTP API
src/bio_pipeline_manager/ Shared Python service/domain layer
```

`labUtils` remains external. The manager stores YAML files, validates them, queues
jobs, records state, captures logs, and invokes `labUtils` through the active Python
environment.

## Backend

The backend follows the same shape as `RLALab-AI-Assistant`:

```text
backend/app/
  main.py                 FastAPI app, CORS, router registration
  core/config.py          Environment-backed settings
  api/deps.py             Shared FastAPI dependencies
  api/routes/             Route modules grouped by responsibility
  schemas/                Pydantic request/response models
  services/runtime.py     Wires stores, queues, and filesystem state
```

Route separation:

```text
/api/v1/pipeline-yamls    YAML storage and retrieval
/api/v1/validation        YAML validation and inspection
/api/v1/jobs              Job submission, queue execution, logs, cancellation
/api/v1/templates         Starter YAML templates
```

The backend does not directly implement pipeline semantics. It delegates to the
shared service layer and ultimately runs `labUtils` as the execution engine.

## Shared Service Layer

The shared package lives in:

```text
src/bio_pipeline_manager/
```

Important modules:

```text
yaml_store.py             Filesystem-backed YAML persistence
yaml_validation.py        Schema-aware labUtils YAML inspection
templates.py              Built-in YAML templates
storage.py                SQLite job state
job_queue.py              Due-job queue runner
runner.py                 Local subprocess backend for labUtils execution
client.py                 Notebook/script HTTP client
cli.py                    Command-line interface
```

This layer is intentionally framework-light. The FastAPI backend, CLI, and Jupyter
client should all use this same logic.

## Frontend

The frontend is a separate Next.js + TypeScript app:

```text
frontend/src/
  app/                    Next App Router entry points
  lib/api.ts              Typed API client
  types/                  Shared frontend TypeScript types
  components/pipelines/   Pipeline manager UI components
```

The frontend deliberately separates the three main workflows:

```text
YamlStoragePanel          Create, load, save, and template YAML files
ValidationPanel           Validate YAML content and inspect issues
JobExecutionPanel         Submit, schedule, run, cancel, and view logs
```

These panels call separate API functions in `frontend/src/lib/api.ts`, which map to
separate backend route groups. This keeps YAML authoring independent from validation,
and validation independent from job execution.

## Runtime Flow

```text
User
  |
  v
Frontend panel
  |
  v
Typed API function
  |
  v
FastAPI route
  |
  v
Shared service layer
  |
  v
Filesystem / SQLite / labUtils subprocess
```

For example, submitting a job follows this path:

```text
JobExecutionPanel
  -> submitJob()
  -> POST /api/v1/jobs
  -> JobQueue.submit()
  -> JobStore.create_job()
```

Running queued jobs follows:

```text
JobExecutionPanel
  -> runDueJobs()
  -> POST /api/v1/jobs/run-due
  -> JobQueue.run_due()
  -> LocalSubprocessRunner.run()
  -> python -m labUtils.scripts.run_a_pipeline ...
```

## Development Commands

Backend:

```bash
source .venv/bin/activate
uvicorn app.main:app --app-dir backend --reload --port 8005
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Tests:

```bash
source .venv/bin/activate
pytest

cd frontend
npm run type-check
npm test
```
