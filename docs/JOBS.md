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
  run_tag: [run-three-replicates, run-five-replicates]
  variant:
    - {name: no_replicates,   pipeline: growth_rate_fit_pipeline}
    - {name: replicates,      pipeline: growth_rate_replicates_fit_pipeline}
    - {name: post_replicates, pipeline: growth_rate_post_replicates_fit_pipeline}

defaults:                           # optional: shared, templated values (see §5)
  data_root: "H:/ROBOT_SCIENTIST/E_coli/Growth_rates/{run_tag}"

stages:                             # required: one or more ordered steps
  - name: preprocess                # required: unique stage name
    pipeline_yaml: growth_rates_pipeline.yaml   # required: stored YAML name
    pipeline: "{variant.pipeline}"  # required: pipeline name inside that YAML
    fanout:                         # optional (default {type: none}); see §4
      type: mapping_file
      mapping: mapping.yaml
      data_dir: "{data_root}/data"
    output_dir: "{data_root}/processed/{variant.name}/{item.stem}"  # required
    input_sources:                  # optional: override pipeline inputs
      raw_data:  "{data_dir}/{item.raw}"
      meta_data: "{data_dir}/{item.meta}"

  - name: collate
    needs: [preprocess]             # optional: run after these stages (same cell)
    pipeline_yaml: collateing_pipeline.yaml
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
> error (HTTP 400), not a server crash. `none` needs no files. A source whose value
> is the `$WILL_PROVIDE$` placeholder is the exception: it is **mocked** with one
> record at validation time and supplied by a researcher when published (see §12).

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

Example resolution for cell `(run_tag=run-three-replicates, variant=no_replicates)`,
item `mediabotJLF1.csv`:

```
output_dir   "{data_root}/processed/{variant.name}/{item.stem}"
          →  "H:/.../run-three-replicates/processed/no_replicates/mediabotJLF1"
input.raw    "{data_dir}/{item.raw}"
          →  "H:/.../run-three-replicates/data/mediabotJLF1.csv"
```

---

## 6. Passing values into the pipeline

A Task feeds two things into the pipeline build:

### `input_sources` — point each input at a concrete file

Every pipeline YAML has an `Inputs` section. Each named input carries, among
other fields, a `src` that tells the engine which file to read:

```yaml
# growth_rates_pipeline.yaml
pipelines:
  - growth_rate_fit_pipeline:
      Inputs:
        - raw_data:
            - src: EMPTY          # no default path — must be supplied at run time
            - package: labUtils.media_bot
            - method: parse_raw_CLARIOstar_export
        - meta_data:
            - src: EMPTY
            - package: labUtils.media_bot
            - method: parse_protocol_metadata
```

`src: EMPTY` is the convention for inputs that have no meaningful default —
the pipeline cannot run until a real path is provided. `input_sources` is how
the Job Definition supplies those paths (and when that path is one a *researcher*
fills in via a published job, the Job Definition uses `$WILL_PROVIDE$` for it —
see §12):

```yaml
# in the stage definition
input_sources:
  raw_data:  "{data_dir}/{item.raw}"
  meta_data: "{data_dir}/{item.meta}"
```

At build time the engine replaces each named input's `src` with the value from
`input_sources`. Keys that are absent from `input_sources` keep whatever `src`
the pipeline YAML declares (useful when only *some* inputs need overriding).
Supplying a key that doesn't match any `Inputs` name has no effect and is
silently ignored.

**When you must provide `input_sources`:** any input with `src: EMPTY` (or
with no `src` at all) will cause the engine to raise a validation error if no
override is given. For a fan-out stage, `input_sources` is almost always
required because each Task's file path is different and comes from
`{item.raw}` / `{item.meta}` / `{item.path}`.

`input_sources` is equivalent to passing `-i NAME=PATH` on the ad-hoc CLI.

### `process_arg_mapping` — override process parameters

Overrides parameters of named *processes*. Shape is
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
descriptive `detail`; a definition still containing `$WILL_PROVIDE$` also returns
**400** (publish it instead — see §12). The same endpoints exist (without the
`/api/v1` prefix) on the lightweight notebook server.

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
- **Submit** — queue the group; it appears under "Submitted jobs". Disabled when
  the definition contains `$WILL_PROVIDE$` — publish it and run it from the
  *Published Jobs* page instead (see §12).
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
| 400 *"… `$WILL_PROVIDE$` placeholder value(s) … cannot be submitted directly"* | The definition has deferred values — publish it and run it from the *Published Jobs* page instead of submitting directly (see §12). |
| 400 *"… placeholder value(s) that were not provided: …"* | A published job was run with a `$WILL_PROVIDE$` value left unfilled or never exposed as a field — provide it, or expose it in the admin page (see §12). |
| Task `blocked` | An upstream Task in the same cell did not succeed — inspect that Task's log. |

---

## 12. Published jobs — researcher-supplied inputs & outputs

A **published job** wraps a Job Definition in a small form so a researcher can run
it without seeing (or editing) any YAML. An admin curates a list of **fields**;
each field's value is spliced into the definition before it expands. Path-like
fields (`file`, `directory`, `path`) can be marked as **researcher inputs or
outputs**, so a remote researcher supplies her own data and gets results back —
without the server filesystem ever being exposed.

### Deferred values — `$WILL_PROVIDE$` (researcher-supplied)

Some values aren't known when the definition is authored because a **researcher
supplies them at run time** — most often a fan-out source like a `mapping_file`
mapping or a `data_dir`, or a shared `data_root`. Mark any such value with the
placeholder `$WILL_PROVIDE$`:

```yaml
defaults:
  data_root: $WILL_PROVIDE$                       # researcher provides the data folder
  data_to_metadata_mapping_yaml: $WILL_PROVIDE$   # researcher provides the mapping
```

The placeholder changes three behaviors:

1. **Validation is mocked, not failed.** When a fan-out source contains
   `$WILL_PROVIDE$`, the expander does **not** touch the filesystem; it fills the
   fan-out with a **single mock record** so the per-item templates
   (`{item.raw}` / `{item.meta}` / `{item.stem}` / `{item.path}` …) still resolve.
   Preview shows one representative Task per cell instead of the *"could not read
   mapping file"* error you would otherwise get for a path that does not exist yet.
2. **Direct submission is blocked.** A definition that still contains
   `$WILL_PROVIDE$` cannot be submitted from the CLI, the *Job Definitions* page,
   or the API — running it would queue the mock placeholder. The Submit button is
   disabled and the API returns **400**. The job must be **published** and run from
   the *Published Jobs* page instead.
3. **The published form fills it in.** Each `$WILL_PROVIDE$` value must be
   **exposed as a field** (selected in the *Published Jobs Admin* page). When the
   researcher provides a value it replaces the placeholder *before* the definition
   expands, and the real fan-out source is read at run time. The admin page warns
   about any placeholder value not yet selected as a field, and clears the warning
   once it is.

If a published job is run with a placeholder still unfilled — the researcher left
a field blank, or the admin never exposed it as a field — submission fails with a
clear, named error (e.g. *"… placeholder value(s) that were not provided:
defaults.data_root"*), **not** the generic "submit directly" message.

> **`$WILL_PROVIDE$` vs `EMPTY`.** These solve different problems. `EMPTY` (§6) is
> a *pipeline* convention: an `Inputs` `src: EMPTY` has no default path and must be
> filled by a stage's `input_sources`. `$WILL_PROVIDE$` is a *Job Definition*
> convention: a value a **researcher** supplies through a published job, mocked
> during validation and barred from direct submission. A stage often uses both — its
> `input_sources` feeds a pipeline's `EMPTY` input from a `{data_root}` that is
> itself `$WILL_PROVIDE$`.

### Field I/O classification (admin, at publish time)

Each field carries an `io_role` and related attributes (set in the *Published
Jobs Admin* page):

| Attribute | Meaning |
|-----------|---------|
| `io_role` | `none` (a plain value / server-managed — default), `input` (researcher provides), or `output` (returned to the researcher). |
| `accept` | `file` or `directory` — what the input/output is. |
| `sources` | For inputs: any of `upload` (from her machine) and `shared` (pick from a server-mounted share). |
| `delivery` | For outputs: any of `download` (zipped artifact) and `shared` (written to a share). |
| `shared_roots` | The allowlisted shared-root `id`s this field may browse / write to. |

The inspector proposes sensible defaults (an input `src` → input/file; a stage
`output_dir` → output/directory), but an ambiguous `path` stays `none` until the
admin classifies it. **A "merges-later" path fragment (e.g. a `data_root`) should
stay `none`** — it is server-managed, never shown as a browsable path.

### What the researcher does

On the *Published Jobs* page each input field offers, per its `sources`:

- **Upload from computer** — a file, or a folder (`accept: directory`). Uploads
  stream in chunks (resumable-friendly); folders preserve their structure.
- **Choose from shared storage** — a modal that browses **only within** the
  allowlisted roots the field declares. Nothing else on the server is visible.

Output fields just show how results will come back. The researcher clicks
*Execute Job*.

### How it runs

1. A per-run **workspace** is reserved under `<pipeline_home>/runs/<id>/{inputs,outputs}`.
2. Uploaded files land in `inputs/`; shared picks are referenced in place (no copy).
3. At submit, each field value is resolved to a concrete path **before** the
   definition renders — so every fan-out Task of the run shares one workspace
   root. Inputs → the uploaded file/folder or the shared path; outputs → a
   workspace `outputs/<field>` directory.

### Getting results back

When the run's task group reaches a terminal state, a background **reaper**:

- zips the outputs into a results archive — the *My Runs* page shows a
  **Download results** link (retained for `artifact_ttl_hours`);
- copies any `delivery: shared` output onto its allowlisted root at
  `<root>/bio_pipeline_outputs/<run_id>/<field>/`;
- deletes the run's inputs, and removes the whole workspace after the TTL.

> A server cannot silently write to a remote machine's disk, so "download" is a
> browser download (or the retained link); the optional shared-write is the
> second delivery channel.

### Where files live & when they're deleted

Every run's uploads, outputs and downloadable archive live in an isolated
workspace **on the backend host**, under the pipeline home:

```
<pipeline_home>/runs/<workspace_id>/
  manifest.json      # owner + metadata (bookkeeping; not counted against quota)
  inputs/            # uploaded files / folders for this run
  outputs/<field>/   # what the job writes for each output field
  artifact.zip       # outputs packaged for download (created after completion)
  .reaped            # timestamp marker written once the run is delivered
```

`pipeline_home` defaults to `<repo>/.bio_pipeline` (configurable via
`backend.pipeline_home`), so a typical archive path is
`.bio_pipeline/runs/<workspace_id>/artifact.zip`. The download endpoint streams
that file — it is never exposed by path, and only the run's owner can fetch it.

A background **reaper** (`run_reaper.py`, polling every `reaper_interval`, default
5s) drives retention:

| Item | Removed when |
|------|--------------|
| `inputs/` (uploaded files) | As soon as the run reaches a terminal state — they are no longer needed. |
| `artifact.zip`, `outputs/`, the whole `runs/<id>/` workspace | `artifact_ttl_hours` after completion (default **24h**). |
| The whole workspace, early | Immediately when the researcher deletes the run (My Runs → Delete). |
| Shared-write copy at `<root>/bio_pipeline_outputs/<run_id>/<field>/` | **Never** — it is permanent, owned by the lab on the share. |

Two nuances:

- The TTL is measured from **completion**, not from download. Downloading does
  not extend it, and the archive is removed ~`artifact_ttl_hours` after the run
  finishes whether or not it was fetched (the "retained link with a TTL" model).
- A genuinely shared *input* (picked from a share, not uploaded) is referenced in
  place and never copied into the workspace, so nothing is deleted for it.

These are tuned by `artifact_ttl_hours`, `reaper_interval` and `reaper_enabled`
(see *Configuration* below); set `reaper_enabled: false` to retain everything
(e.g. for debugging) at the cost of unbounded disk growth.

### Tracking a run (My Runs)

The *My Runs* page lists the researcher's runs. Each row has a leftmost
checkbox (for multi-select **Delete selected**) and an actions column; clicking a
run expands a panel **below the row** showing the run's **Download results** link
(when ready) and its individual tasks. Each task carries a circular show/hide
toggle that reveals that task's log inline. Deleting a run cancels any active
tasks and removes its task records, logs and workspace files.

### Security

- Every caller-supplied path (workspace id, upload filename/relpath, shared
  sub-path) is containment-checked; `..`, absolute paths and zip-style escapes
  are rejected.
- Shared browsing/writing is limited to admin-declared roots, and further to the
  roots a given field lists. A workspace is owned by the submitting user.
- A per-run upload **quota** (`upload_max_bytes`) is enforced while streaming.

### Configuration (`configs/app_config.yaml`, `backend`)

```yaml
shared_roots:
  - id: robot_scientist_ecoli
    label: "E. coli growth data"
    path: "H:/ROBOT_SCIENTIST/E_coli"
upload_max_bytes: 2147483648   # per-run upload budget (default 2 GiB)
artifact_ttl_hours: 24         # how long a results archive / workspace is kept
reaper_enabled: true
reaper_interval: 5.0
```

### Limitation

**Rewind** is disabled for runs that used a workspace (uploaded inputs or
returned outputs): the original paths are cleaned up after completion, so a
replay would reference files that no longer exist. Start a fresh run from the
published job to provide inputs again.
```
