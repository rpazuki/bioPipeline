# Jobs — Scheme, Meaning, and Usage

This guide explains how "jobs" work in Bio Pipeline Manager: the data model, the
declarative **Job Definition** YAML, how it expands into runnable tasks, and how
to use it from the CLI, HTTP API, notebook client, and web UI.

For the design rationale and rollout history see [`JOBS_REDESIGN.md`](JOBS_REDESIGN.md).
This document is the practical reference.

---

## 1. The model at a glance

A real experiment is more than one pipeline run. The manager models it as a
three-level hierarchy:

```
Job Definition  (one declarative YAML file)
  └── Stages           ordered steps; a later stage can wait for an earlier one
        └── Tasks       one fully-resolved pipeline invocation (the unit that runs)
```

- A **Task** is the atom: a single pipeline executed once, with a concrete
  `output_dir`, `input_sources`, and `process_arg_mapping`. Each Task has its own
  status and log.
- A **Stage** applies one pipeline (from its own pipeline YAML) over a *fan-out*
  of items (e.g. one Task per data file), and may declare `needs:` to run after
  other stages.
- A **Job Definition** sweeps the stages across a **matrix** of variables and
  groups all resulting Tasks under one parent job with a rollup status.

Submitting one Job Definition therefore queues many Tasks at once. This single
file replaces the hand-written loop scripts (`*.py`) and batch files (`*.bat`)
that used to run a pipeline repeatedly across files and settings.

---

## 2. The Job Definition YAML

```yaml
job: growth_rates_full              # required: the job's name
description: Preprocess + collate   # optional

variables:                          # optional: the matrix (see §3)
  run_tag: [Anthony-Three-Replicates, Anthony-Five-Replicates]
  variant:
    - {name: no_replicates,   pipeline: growth_rate_fit_pipeline}
    - {name: replicates,      pipeline: growth_rate_replicates_fit_pipeline}
    - {name: post_replicates, pipeline: growth_rate_post_replicates_fit_pipeline}

defaults:                           # optional: shared, templated values (see §5)
  data_root: "H:/ROBOT_SCIENTIST/E_coli/Growth_rates/{run_tag}"

stages:                             # required: one or more ordered steps
  - name: preprocess                # required: unique stage name
    pipeline_yaml: Anthony_growth_rates_pipeline.yaml   # required: stored YAML name
    pipeline: "{variant.pipeline}"  # required: pipeline name inside that YAML
    fanout:                         # optional (default {type: none}); see §4
      type: mapping_file
      mapping: Anthony_mapping.yaml
      data_dir: "{data_root}/data"
    output_dir: "{data_root}/processed/{variant.name}/{item.stem}"  # required
    input_sources:                  # optional: override pipeline inputs
      raw_data:  "{data_dir}/{item.raw}"
      meta_data: "{data_dir}/{item.meta}"

  - name: collate
    needs: [preprocess]             # optional: run after these stages (same cell)
    pipeline_yaml: Anthony_collateing_pipeline.yaml
    pipeline: collate_per_strain_pipeline
    fanout: {type: none}
    input_sources:
      folders_list: "{data_root}/processed/{variant.name}"
    process_arg_mapping:            # optional: per-process parameter overrides
      saved_dataframes:
        strain_col: strain
        csv_input_file_name: growth_rates.csv
    output_dir: "{data_root}/processed/{variant.name}_STRAINS"
```

### Top-level keys

| Key | Required | Meaning |
|-----|----------|---------|
| `job` | yes | The job name (shown in listings and rollups). |
| `description` | no | Free text. |
| `variables` | no | The matrix; each value is a non-empty list (see §3). |
| `defaults` | no | Shared values, templated per matrix cell (see §5). |
| `stages` | yes | A non-empty, ordered list of stages. |

### Stage keys

| Key | Required | Meaning |
|-----|----------|---------|
| `name` | yes | Unique within the definition; used by `needs:` and in the UI. |
| `pipeline_yaml` | yes | Name of a **stored** pipeline YAML (resolved against the YAML store). |
| `pipeline` | yes | The pipeline name to run inside that YAML. |
| `output_dir` | yes | Output directory for this stage's Tasks (templated). |
| `fanout` | no | How to fan out into Tasks; default `{type: none}` (see §4). |
| `input_sources` | no | Overrides for the pipeline's `Inputs` `src` values (templated). |
| `process_arg_mapping` | no | Per-process parameter overrides (templated; see §6). |
| `needs` | no | List of stage names this stage waits for, within the same matrix cell. |

> `pipeline_yaml` must be a name inside the YAML store (e.g. `growth.yaml` or
> `designs/alpha/growth.yaml`). Paths that escape the store are rejected.

---

## 3. Variables — the matrix

`variables` is expanded into the **cartesian product** of all its lists. Each
combination is one *cell*, and every stage runs once per cell.

A variable value is either:

- a **scalar** — referenced as `{run_tag}`; or
- a **mapping (dict)** — referenced field-by-field as `{variant.name}`,
  `{variant.pipeline}`, …

```yaml
variables:
  run_tag: [A, B]                          # scalar
  variant:
    - {name: x, pipeline: p1}              # dict
    - {name: y, pipeline: p2}
```

This yields 2 × 2 = 4 cells: `(A,x) (A,y) (B,x) (B,y)`. With no `variables`,
there is exactly one (empty) cell.

Each Task records its `matrix_key` — the cell it belongs to. For a dict variable,
the key uses its `name` field (e.g. `variant=x`).

---

## 4. Fan-out — one stage, many Tasks

A stage's `fanout` decides how many Tasks it produces per cell and what
per-item fields are available for templating.

| `type` | Extra keys | Tasks produced | Item fields exposed |
|--------|-----------|----------------|---------------------|
| `none` (default) | — | exactly 1 | (none) |
| `mapping_file` | `mapping`, `data_dir`? | one per `raw → meta` pair | `{item.raw}`, `{item.meta}`, `{item.stem}`, `{item.name}` |
| `patterns` | `data_dir`, `raw_pattern`, `meta_pattern` | one per matched, sorted pair | same as `mapping_file` |
| `folders` | `data_dir` | one per sub-folder of `data_dir` | `{item.path}`, `{item.name}`, `{item.stem}` |

- **`mapping_file`** reads a mapping file (`.yaml`, `.csv`, or `.py`) of
  `raw_data_file: metadata_file` entries — the same mapping format used by the
  legacy preprocessing scripts.
- **`patterns`** globs `raw_pattern` and `meta_pattern` inside `data_dir` and
  pairs them in sorted order.
- **`folders`** makes one Task per immediate sub-directory of `data_dir`
  (useful for "collate everything under this folder").

> A stage's fan-out reads the filesystem on the machine running the backend when
> the stage is **materialised**: at submit for eligible (first) stages, and at run
> time for stages gated behind `needs` (so a source produced upstream is fine —
> see §8). A genuinely missing source on a first stage gives a clear validation
> error (HTTP 400), not a server crash. `none` needs no files.

`data_dir`, when present, is itself templated and is also exposed to
`input_sources`/`output_dir` templates as `{data_dir}`.

---

## 5. Templating

Any string in a stage (`pipeline`, `pipeline_yaml`, `output_dir`,
`input_sources`, `process_arg_mapping`) may contain `{token}` substitutions.
Tokens are resolved against, in order of availability:

1. **Matrix bindings** — `{run_tag}`, `{variant.name}`, `{variant.pipeline}`.
2. **Defaults** — `{data_root}`. Defaults are rendered in declaration order, so a
   later default may reference an earlier one.
3. **Stage `data_dir`** — `{data_dir}` (if the fan-out declares one).
4. **Per-item fields** — `{item.raw}`, `{item.stem}`, `{item.path}`, … (see §4).

An unknown token (e.g. `{typo}`) is a validation error. There is no code
execution — substitution is pure string replacement that produces concrete
paths and values.

Example resolution for cell `(run_tag=Anthony-Three-Replicates, variant=no_replicates)`,
item `mediabotJLF1.csv`:

```
output_dir   "{data_root}/processed/{variant.name}/{item.stem}"
          →  "H:/.../Anthony-Three-Replicates/processed/no_replicates/mediabotJLF1"
input.raw    "{data_dir}/{item.raw}"
          →  "H:/.../Anthony-Three-Replicates/data/mediabotJLF1.csv"
```

---

## 6. Passing values into the pipeline

A Task feeds two things into the pipeline build:

- **`input_sources`** — overrides the `src` of named pipeline `Inputs`. Equivalent
  to `-i NAME=PATH`. Use it to point the pipeline at this Task's specific files.
- **`process_arg_mapping`** — overrides parameters of named *processes*. Shape is
  `{process_name: {param: value}}`. This is how per-strain / per-column settings
  are passed (the collate workflow), and it is the capability the old
  `run_a_pipeline` CLI could not express.

Both are templated, so they can reference matrix and item fields.

### Data flow between stages

Each Task runs in its own isolated subprocess, so stages hand data to each other
**through the filesystem**, not in memory: a later stage's `input_sources`
typically points at an earlier stage's `output_dir`. In the example, `collate`
reads `{data_root}/processed/{variant.name}` — the directory `preprocess` wrote.
A chained pipeline must therefore *write* what the next one *reads*.

---

## 7. Dependencies and ordering

`needs:` lists the stages a stage must wait for **within the same matrix cell**.
Cells are independent — cell `A`'s `collate` never waits on cell `B`'s
`preprocess`. When a stage fans out into several Tasks, a dependent stage waits
for **all** of them in its cell.

At execution time the queue is dependency-aware:

- A Task runs only once **all** its upstream Tasks have **succeeded**.
- If any upstream Task ends in `failed` / `cancelled` / `blocked`, the dependent
  Task is moved to **`blocked`** (it will never run). Blocking cascades downstream.
- A Task still waiting on running/queued upstreams is simply skipped that round.

---

## 8. Lifecycle and statuses

### Task statuses

| Status | Meaning |
|--------|---------|
| `queued` | Waiting to run (or waiting on a schedule / dependencies). |
| `running` | Subprocess in progress. |
| `succeeded` | Exited 0. |
| `failed` | Exited non-zero. |
| `cancelled` | Cancelled by the user (subprocess killed if it was running). |
| `blocked` | An upstream dependency did not succeed; will not run. |

### Group (Job Definition) rollup

The parent job's status is derived from its Tasks:

| Rollup | When |
|--------|------|
| `queued` / `running` | Some Tasks are still queued / running. |
| `succeeded` | All Tasks succeeded. |
| `partially_failed` | Some succeeded **and** some failed/blocked/cancelled. |
| `failed` | All terminal, none succeeded. |

### Expansion model

The matrix is expanded **eagerly** at submit (every cell), but each stage's
fan-out is materialised **lazily**: only stages that are immediately eligible
(no unmet `needs`) are queued at submit; a downstream stage is materialised when
its upstream stages in the same cell have **succeeded**. This means a stage whose
`folders`/`patterns` source is *produced by an upstream stage at run time* works
fine — the source need not exist at submit. Consequences:

- The total task count of a group **grows over time** as stages materialise.
- If an upstream stage fails, the downstream stage is materialised as a single
  **`blocked`** placeholder (it never runs) so it stays visible in the rollup.
- **Preview** is lenient: a downstream stage whose source isn't available yet is
  shown as one `deferred` entry (it "fans out at run time") rather than failing.
  A *first* stage with a missing source is still a real error.

---

## 9. Usage

### CLI

```bash
# Expand and inspect a definition without running anything:
bio-pipeline job preview growth_rates_full.yaml

# Expand and queue it as one parent group:
bio-pipeline job submit growth_rates_full.yaml          # prints the parent job id
bio-pipeline job submit growth_rates_full.yaml --at 2026-06-07T08:00:00

# Drain the queue (respects dependencies); run repeatedly or rely on the worker:
bio-pipeline run-due --parallel 2

# Roll-up status + per-task breakdown for a submitted group:
bio-pipeline job status <PARENT_JOB_ID>
```

Ad-hoc single Tasks (no definition) still work:

```bash
bio-pipeline submit growth.yaml growth_rate_fit_pipeline \
  --output-dir ./out \
  -i raw_data=data/mediabot.csv \
  -p saved_dataframes.strain_col=strain
```

### HTTP API (backend, prefix `/api/v1`)

| Method & path | Purpose |
|---------------|---------|
| `POST /job-definitions/preview` | Expand a definition; returns the task list. Body: `{ "content": "<yaml>" }`. |
| `POST /job-definitions` | Submit; returns the group rollup + tasks. Body: `{ "content": "<yaml>", "scheduled_at": null }`. |
| `GET /job-definitions` | List submitted groups with rollup status/counts. |
| `GET /job-definitions/{parent_job_id}` | Group detail with per-task records. |

Malformed definitions or unreadable fan-out sources return **400** with a
descriptive `detail`. The same endpoints exist (without the `/api/v1` prefix) on
the lightweight notebook server.

### Notebook client

```python
from bio_pipeline_manager import PipelineClient

client = PipelineClient("http://127.0.0.1:8005")
preview = client.preview_definition(open("growth_rates_full.yaml").read())
group   = client.submit_definition(open("growth_rates_full.yaml").read())
client.run_due()                      # or rely on the background worker
client.get_definition(group["parent_job_id"])
```

### Web UI

Open the **Job Definitions** page (`/job-definitions`). Paste or edit a
definition, then:

- **Preview** — see the expanded Tasks (stage, matrix cell, pipeline, output dir)
  without queueing.
- **Submit** — queue the group; it appears under "Submitted jobs".
- **Run due** — drain the queue.
- Click any submitted job to see the hierarchical view: stages → per-cell Tasks
  with their statuses and the group rollup.

---

## 10. Worked example → what it replaces

The definition in §2 expands (for the full matrix) to:

```
2 run_tags  ×  3 variants  ×  (N mapping pairs for preprocess  +  1 collate)
```

Tasks, where every collate Task waits on all preprocess Tasks of its cell. That
one file replaces:

| Legacy construct | Job Definition equivalent |
|------------------|---------------------------|
| `.bat` `RUN_TAG` loop | `variables.run_tag` |
| `.bat` three `--pipeline=` lines | `variables.variant[].pipeline` |
| `.bat` templated `H:\...\{RUN_TAG}\...` paths | `defaults.data_root` + `{run_tag}` |
| `preprocessing_pipeline.py` mapping loop | stage `preprocess`, `fanout.type: mapping_file` |
| per-file `output_dir = base/stem` | `output_dir: "{...}/{item.stem}"` |
| per-file `input_sources` | stage `input_sources` with `{item.raw/meta}` |
| `collate_per_strain_pipeline.py` `process_arg_mapping` | stage `process_arg_mapping` |
| preprocess-then-collate ordering | `collate.needs: [preprocess]` |
| the scripts' success/fail summary | the group rollup + per-task statuses |

---

## 11. Common errors

| Symptom | Cause / fix |
|---------|-------------|
| 400 *"could not read mapping file …"* | The `mapping_file` path is missing on the backend host. Use a path reachable by the backend, or `fanout: {type: none}`. |
| 400 *"unresolved template variable `{x}`"* | A `{token}` doesn't match any variable/default/item field. |
| 400 *"stage '…' needs unknown stage '…'"* / *"dependency cycle"* | Fix the `needs:` references. |
| 400 *"YAML name must be relative and stay inside the YAML store"* | `pipeline_yaml` must name a stored YAML, not an absolute/escaping path. |
| Task `blocked` | An upstream Task in the same cell did not succeed — inspect that Task's log. |
```
