# Bio Pipeline Manager

Lightweight YAML authoring, queueing, scheduling, and execution tooling for existing
`labUtils` pipelines.

The process/YAML pipeline engine lives in this project's `pipeline` package (transferred
from `labUtils`). Each job runs as an isolated subprocess that builds and executes the
pipeline in-process via the engine:

```bash
python -m bio_pipeline_manager.run_task TASK.json
```

This lets a job carry `process_arg_mapping` (per-process parameter overrides), which the old
`labUtils.scripts.run_a_pipeline` CLI never exposed. The **science** process functions still
live in `labUtils`, installed separately and referenced from YAML as `package: labUtils.*`.
See `docs/JOBS_REDESIGN.md` for the full design.

## Project Shape

The project is split into:

- `backend/` — FastAPI app following the `RLALab-AI-Assistant` route/schema/settings pattern.
- `frontend/` — Next.js + TypeScript frontend following the same library choices.
- `src/bio_pipeline_manager/` — shared lightweight service/domain code used by the backend and notebook client.
- `tests/` and `backend/tests/` — unit and e2e coverage.

The frontend treats YAML storage, YAML validation, and job execution as separate flows.

Storage is tree-based: users organize YAML files in folders, select files from the tree, and create folders from the Storage page. New or edited YAML files are saved from the Validation page, which is now the only save surface.

## Development Setup

Create and activate the development environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,api]"
```

For local co-development, install `labUtils` into the same environment as an
external editable package:

```bash
python -m pip install -e "/Users/roozbeh/Research/Geoff Lab/projects/lab_utils/src"
```

This is the preferred development setup here because changes in `lab_utils` are
immediately visible to the manager subprocess runner.

For deployed environments, install `labUtils` from GitHub instead:

```bash
python -m pip install -e ".[api,labutils]"
```

or install `labUtils` directly:

```bash
python -m pip install "labUtils @ git+https://github.com/rpazuki/lab_utils.git#subdirectory=src"
```

The `#subdirectory=src` part matters because the `labUtils` package metadata lives
inside the repository's `src/` directory.

Run tests:

```bash
pytest
```

## Unified Configuration

Project configuration is centralized in:

```bash
configs/app_config.yaml
```

This file contains both `frontend` and `backend` sections with:

- `shared` values used by all environments
- environment-specific overrides under `development` and `production`

Profile selection priority is:

1. `APP_ENV`
2. `defaults.environment` in `configs/app_config.yaml`

Backend and frontend both support direct environment-variable overrides for deployed setups.
For example:

```bash
APP_ENV=production
NEXT_PUBLIC_API_URL=https://api.my-domain.example
```

In production profiles, API docs are disabled by setting:

```yaml
backend:
  production:
    docs_url: null
    redoc_url: null
```

## CLI Examples

Initialize local state folders:

```bash
bio-pipeline init
```

Create the first admin account:

```bash
bio-pipeline auth bootstrap-admin --username admin
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

Serve the backend API:

```bash
uvicorn app.main:app --app-dir backend --reload --reload-dir backend --reload-dir src --port 8006
```

`--reload-dir backend --reload-dir src` keeps the auto-reloader watching only the
source trees. Without it the reloader also watches `.venv`, so installing a
package from the Environment page churns `site-packages` and restarts the worker
mid-install.

Run the frontend:

```bash
cd frontend
npm install
npm run dev
```

Validate a stored YAML:

```bash
bio-pipeline yaml validate growth.yaml
```

List templates:

```bash
bio-pipeline template list
```

Use the notebook/client API:

```python
from bio_pipeline_manager import PipelineClient

client = PipelineClient("http://127.0.0.1:8005")
client.save_yaml("growth.yaml", yaml_text)
report = client.validate_yaml(yaml_text)
job = client.submit("growth.yaml", "growth_rate_fit_pipeline", "./outputs/run-001")
client.run_due()
client.logs(job["id"])
```

## Project Layout

```text
docs/
  PLAN.md
backend/
  app/
    api/routes/
    core/
    schemas/
    services/
frontend/
  src/
    app/
    components/pipelines/
    lib/
    types/
src/bio_pipeline_manager/
  cli.py
  client.py
  job_queue.py
  models.py
  runner.py
  storage.py
  templates.py
  yaml_store.py
  yaml_validation.py
tests/
  unit/
  e2e/
```

## Design Principle

The manager owns the pipeline engine (`pipeline` package) plus the surrounding operational
concerns: YAML files, queue state, scheduling, logs, and execution backends. `labUtils`
remains the source of truth for the **science** process functions referenced from YAML.

## Custom Pipeline Functions

Project-level reusable process functions live under:

src/pipeline/helpers/

Use them directly in YAML with:

- package: pipeline.helpers
- method: function_name

Example:

```yaml
pipelines:
  - demo_pipeline:
      Inputs: []
      Processes:
        - generated_numbers:
            package: pipeline.helpers
            method: sequence
            parameters:
              start: 0
              stop: 5
              step: 1
        - saved_path:
            package: pipeline.helpers
            method: save_text
            parameters:
              text: "pipeline run complete"
              path: "outputs/run-001/message.txt"
      Outputs: []
```

Built-in functions currently exposed from this package:

- ensure_list
- sequence
- format_message
- save_text
