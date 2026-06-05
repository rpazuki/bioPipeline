# Bio Pipeline Manager

Lightweight YAML authoring, queueing, scheduling, and execution tooling for existing
`labUtils` pipelines.

This project does not reimplement the `labUtils` pipeline engine. It treats `labUtils`
as an external library and runs pipelines through:

```bash
python -m labUtils.scripts.run_a_pipeline PIPELINE.yaml PIPELINE_NAME -o OUTPUT_DIR
```

## What Exists In This Skeleton

- YAML storage and validation for `labUtils` pipeline YAML files.
- SQLite-backed job state.
- Local subprocess execution backend.
- Basic due-job queue runner with configurable parallelism.
- A small CLI.
- A FastAPI app skeleton.
- Unit and e2e tests that do not require the real `labUtils` repo.

## Development Setup

Create and activate the development environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,api]"
```

Install `labUtils` into the same environment as an external editable package:

```bash
python -m pip install -e "/Users/roozbeh/Research/Geoff Lab/projects/lab_utils/src"
```

Run tests:

```bash
pytest
```

## CLI Examples

Initialize local state folders:

```bash
bio-pipeline init
```

Store a YAML file:

```bash
bio-pipeline yaml save growth.yaml ./my_growth_pipeline.yaml
```

Submit a job:

```bash
bio-pipeline submit growth.yaml growth_rate_fit_pipeline --output-dir ./outputs/run-001
```

Run due queued jobs:

```bash
bio-pipeline run-due --parallel 2
```

List jobs:

```bash
bio-pipeline jobs
```

Serve the API:

```bash
uvicorn bio_pipeline_manager.api.app:create_app --factory --reload
```

## Project Layout

```text
docs/
  PLAN.md
src/bio_pipeline_manager/
  api/
  cli.py
  job_queue.py
  models.py
  runner.py
  storage.py
  yaml_store.py
tests/
  unit/
  e2e/
```

## Design Principle

`labUtils` remains the source of truth for pipeline semantics. This manager owns only
the surrounding operational concerns: YAML files, queue state, scheduling, logs, and
external execution backends.

