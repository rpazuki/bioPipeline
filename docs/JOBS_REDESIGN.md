# Jobs Redesign — Declarative Job Definitions

Status: **design / planning**. Supersedes the single-invocation job model described in
`docs/PLAN.md` (Phase 1). Decisions locked with the user:

- **Scope:** full declarative spec (variable matrix + stages + fan-out + dependencies).
- **Engine:** **transfer the process/YAML engine** (process classes, the YAML→pipeline builders,
  file-mapping helpers) out of `labUtils` into this project's **`pipeline` package under a
  project-native name** — never imported or referred to as `labUtils`. The **science** process
  functions stay in `labUtils`, installed via a new **Package Management** UI page and referenced
  from YAML as `package: labUtils.*`.
- **Execution:** run each Task in an isolated subprocess that calls the **transferred**
  `pipeline` builder (not the `run_a_pipeline` CLI), which supports `process_arg_mapping`.
- **Multi-YAML chaining:** a single Job can sequence pipelines from *different* pipeline YAML
  files — "when one finishes, the next starts" — modelled as ordered **stages** with `needs:`.
- **Expansion:** hybrid — expand the variable matrix eagerly at submit; expand each
  stage's fan-out lazily when that stage becomes eligible.

---

## 1. Motivation: what a "job" really is

Today a job is one flat `JobSpec` → one subprocess
(`python -m labUtils.scripts.run_a_pipeline YAML PIPELINE -o OUT -i k=v`,
see `src/bio_pipeline_manager/models.py:17` and `runner.py:26`). That is only the **leaf**
of the real workflow. The attached experiment scripts reveal three nested levels:

| Level | Source file | What varies |
|-------|-------------|-------------|
| **Task** (one invocation) | `build_pipeline_from_lib_yaml(...)` + `pipeline()` | `output_dir`, `input_sources`, **`process_arg_mapping`** |
| **Fan-out** (the `.py` scripts) | loop over a mapping/glob | per-item `input_sources`, per-item `output_dir = base/{stem}`; collect success/fail |
| **Matrix + stages** (the `.bat` files) | loop over `RUN_TAG` × variant; preprocess **then** collate | `pipeline_name`, pipeline YAML, mapping file, templated `data_dir`/`output_base` |

### Two gaps in today's manager

1. **`process_arg_mapping` is unsupported end-to-end.** `build_pipeline_from_yaml` accepts
   it (`labUtils/utils.py:146`) but `run_a_pipeline.py` only exposes `-i NAME=PATH`
   (`run_a_pipeline.py:69`), and `JobSpec`/`JobStore`/`runner` never carry it. **The collate
   workflow (`collate_per_strain_pipeline.py:103`) cannot run through the manager at all.**
2. **No fan-out, no matrix, no stage ordering.** Each `.bat`/`.py` line would today be dozens
   of hand-submitted single jobs, and "collate after preprocess" cannot be expressed.

---

## 2. Conceptual model: Job → Stages → Tasks

```
Job Definition (declarative YAML, a new artifact, distinct from a pipeline YAML)
  └── variables (the matrix: run_tag × variant × …)        ← expanded EAGERLY at submit
        └── Stage (ordered; `needs:` previous stages)
              └── fan-out (mapping_file | patterns | folders | none)  ← expanded LAZILY
                    └── Task  =  one pipeline invocation
                                  (yaml, pipeline, output_dir,
                                   input_sources, process_arg_mapping)
```

- **Task** is essentially today's `JobSpec` + `process_arg_mapping`. It remains the unit that
  has a status, a log file, a PID, and is claimed/run atomically.
- **Stage** is one pipeline applied via one fan-out strategy. Stages within the same matrix
  cell run in declared order; `needs:` makes a stage wait for upstream stages of *that cell*.
- **Job** is the parent definition + a rollup status over its Tasks
  (`queued` / `running` / `partially_failed` / `succeeded` / `failed`).

One Job Definition replaces **all four attached files** (`run_all_prepocessings.bat`,
`preprocessing_pipeline.py`, `run_all_collate_by_strain.bat`, `collate_per_strain_pipeline.py`).

---

## 3. The new Job Definition YAML

```yaml
job: growth_rates_full
description: Preprocess + collate across replicate variants

variables:                          # the matrix (replaces the .bat loops)
  run_tag: [Anthony-Three-Replicates, Anthony-Five-Replicates]
  variant:
    - {name: no_replicates,   pipeline: growth_rate_fit_pipeline}
    - {name: replicates,      pipeline: growth_rate_replicates_fit_pipeline}
    - {name: post_replicates, pipeline: growth_rate_post_replicates_fit_pipeline}

defaults:
  data_root: "H:/ROBOT_SCIENTIST/E_coli/Growth_rates/{run_tag}"

stages:
  - name: preprocess
    pipeline_yaml: Anthony_growth_rates_pipeline.yaml
    pipeline: "{variant.pipeline}"
    fanout:                         # the .py loop
      type: mapping_file            # mapping_file | patterns | folders | none
      mapping: Anthony_mapping.yaml # raw -> meta pairs (load_file_mapping)
      data_dir: "{data_root}/data"
    output_dir: "{data_root}/processed/{variant.name}/{item.stem}"
    input_sources:
      raw_data:  "{data_dir}/{item.raw}"
      meta_data: "{data_dir}/{item.meta}"

  - name: collate
    needs: [preprocess]             # stage dependency / ordering
    pipeline_yaml: Anthony_collateing_pipeline.yaml
    pipeline: collate_per_strain_pipeline
    fanout: {type: none}            # single invocation
    input_sources:
      folders_list: "{data_root}/processed/{variant.name}"
    process_arg_mapping:            # the missing capability
      saved_dataframes:
        strain_col: strain
        csv_input_file_name: growth_rates.csv
        csv_output_file_name: growth_rates.csv
    output_dir: "{data_root}/processed/{variant.name}_STRAINS"
```

Submitting expands to `2 run_tags × 3 variants × (N mapping pairs + 1 collate)` Tasks, with
each collate Task gated on the matching preprocess Tasks of the same `(run_tag, variant)` cell.

### Templating
- A single `{var}` / `{var.field}` substitution language over: matrix variables, `defaults`,
  and fan-out item fields (`{item.raw}`, `{item.meta}`, `{item.stem}`, `{item.path}`).
- `data_dir` declared in a stage's `fanout` is also exposed to that stage's `input_sources`
  templates (mirrors `preprocessing_pipeline.py:150`).
- Resolution is pure string substitution producing concrete paths — no code execution.

### Fan-out strategies (mirror the `labUtils` helpers)
| `type` | Backed by | Items produced |
|--------|-----------|----------------|
| `mapping_file` | `load_file_mapping` | one item per `raw -> meta` pair; `item.raw`, `item.meta`, `item.stem` |
| `patterns` | `create_file_mapping_from_patterns` | one item per matched raw/meta pair |
| `folders` | `list_folders` | one item per subfolder; `item.path`, `item.name` |
| `none` | — | exactly one item (single invocation) |

### Multi-YAML chaining ("one finishes, the next starts")
A Job can sequence pipelines from **different pipeline YAML files** — each stage names its own
`pipeline_yaml` + `pipeline`, and `needs:` enforces ordering. The two-stage example above already
spans `Anthony_growth_rates_pipeline.yaml` → `Anthony_collateing_pipeline.yaml`.

A *pure* linear chain (no matrix, no fan-out) is just the degenerate case — stages with
`fanout: {type: none}` and linear `needs:`:

```yaml
job: amn_then_report
stages:
  - {name: amn,    pipeline_yaml: Alfie/amn_pipeline.yaml,        pipeline: amn_pipeline,   fanout: {type: none}, output_dir: "out/amn"}
  - {name: report, pipeline_yaml: Alfie/collateing_pipeline.yaml, pipeline: report,         fanout: {type: none}, needs: [amn],
     input_sources: {data: "out/amn"}}
```

**Constraint:** Tasks are isolated subprocesses, so data flows between chained pipelines through
the **filesystem** (stage A's `output_dir` → stage B's `input_sources`), not an in-memory payload.
A chained pipeline must write what the next one reads — exactly how `preprocess → collate` works.

---

## 4. Two layers: transfer the engine, keep `labUtils` for science

The code splits cleanly along an axis that already exists in `labUtils`:

- **Process/YAML engine — transferred into `pipeline`.** The orchestration code (process
  classes, `DFPipeline`, the YAML→pipeline builders, the file-mapping helpers) moves out of
  `labUtils` into this project's **`pipeline` package** under a **project-native name**. After
  the move it is *ours*; it is never named or imported as `labUtils` anywhere in this project.
- **Science process functions — stay in `labUtils`.** `growth_rates`, `media_bot`,
  `amn_mappings`, `synthetic`, `fba`, and the science helpers in `utils.py` (`smart_join`,
  `collate_by_strain`, the compound/ion/MW chemistry). These remain in `labUtils`, installed via
  the Package Management page (§5a), and are referenced from YAML as `package: labUtils.*`.

"Rely on `labUtils`" therefore means: rely on it as the installable home of the **science**
functions — not the engine.

### What transfers, and what it's called
| From `labUtils` | To `pipeline` (new name) | Contents |
|-----------------|--------------------------|----------|
| `pipelines.py` | `pipeline.engine` (e.g.) | `DFPipeline`, `Process`/`Fork`/`Joined`, `Input`/`DF`/`Output` process, `build_pipeline_from_yaml_string` |
| process/yaml helpers in `utils.py` | `pipeline.engine` / `pipeline.io` | `build_pipeline_from_yaml`, `load_file_mapping`, `create_file_mapping_from_patterns`, `list_folders`, `read_csv` |
| (existing) | `pipeline.helpers` | project process functions, unchanged (`README.md:212`) |

`build_pipeline_from_lib_yaml` (which reads `labUtils/yamls/`) is **not** transferred — this
project has its own YAML store, so Tasks always call `build_pipeline_from_yaml` with an explicit
path.

### Resolution boundary
The transferred engine resolves each process's `package:method` **by import at runtime**, so
valid `package` values are whatever is importable in the backend env: `labUtils.*` (science),
`pipeline.helpers` (project), `pandas`, etc. Owning the engine means `process_arg_mapping` and
future features are fully under our control.

### Naming rule
Nothing under `pipeline.*` may be named, aliased, or documented as `labUtils`. The transferred
module is a project component with its own identity; `labUtils` refers *only* to the external,
pip-installed science package.

---

## 5. Execution: isolated subprocess that imports `labUtils` in-process

Replace the `run_a_pipeline`-CLI shell-out with our own task entrypoint that imports the
**installed** `labUtils` builder directly. Keep **subprocess-per-task isolation** (one crashing
task must not take down the worker):

```
python -m bio_pipeline_manager.run_task  <materialized_task.json>
```

`materialized_task.json` carries the fully-resolved Task:
`{yaml_path, pipeline_name, output_dir, input_sources, process_arg_mapping}`.
The module calls `labUtils.utils.build_pipeline_from_yaml(...)` then `pipeline()`, prints the
result-key summary to stdout (captured to the per-task log exactly as today), and exits non-zero
on failure.

Why import the function instead of the CLI: `build_pipeline_from_yaml` **already accepts
`process_arg_mapping`** (`labUtils/utils.py:146`); the `run_a_pipeline` CLI does not expose it
(`run_a_pipeline.py:69`). Importing the builder solves the blocker with **zero `labUtils`
changes and no vendoring**, while still giving us full control over result capture and error
formatting. The subprocess uses `sys.executable`, so it picks up packages installed from the
Package Management page.

---

## 5a. Package Management page

Lets the user install/upgrade the pipeline + science packages (`labUtils` and anything providing
process functions) into the backend's Python environment, from the UI, without shell access.

**Decisions:** single environment (the backend's `sys.executable`); **auth + audit** required.

### Environment
- Exactly one managed environment: the backend interpreter. Installs run
  `sys.executable -m pip install …` so the per-Task execution subprocess
  (`runner.py:23`) and the backend share one site-packages. No venv lifecycle, no per-job env
  selection — keeps `JobSpec` unchanged on this axis.
- After an install the backend calls `importlib.invalidate_caches()`; the UI still shows a
  "restart backend to (re)validate against new packages" hint, because already-imported modules
  are not reloaded in-process. Execution subprocesses are fresh per Task and need no restart.

### Supported install sources
- PyPI name (`addict`), optional version pin (`labUtils==1.2.0`).
- Git URL — required for `labUtils`: `git+https://github.com/rpazuki/lab_utils.git#subdirectory=src`.
- Editable local path (dev): `-e /Users/.../lab_utils/src`.
- `requirements.txt` upload (batch).

### Security (auth + audit)
- The page and its API endpoints require authentication (login/token); anonymous callers are
  rejected. `pip install` is arbitrary code execution, so this gate is mandatory before the
  feature is exposed beyond localhost.
- Every install is **audited**: who, timestamp, exact pip args, requested spec, resolved
  version, exit code, and captured pip stdout/stderr — persisted (new `installs` table) and
  shown as history on the page.
- Installs are **serialized against job execution**: refuse (or queue) installs while Tasks are
  RUNNING to avoid mutating site-packages mid-run.

### API / surface
- `GET /packages` — list installed (name, version, source), plus install history.
- `POST /packages/install` — `{spec, source_type, editable?}` → runs pip, streams/captures
  output to an install log (same pattern as job logs), records an audit row. **Auth required.**
- `POST /packages/uninstall` — `{name}`. **Auth required.**
- Frontend "Environment" page: installed table, install form (source-type aware), live install
  log, audit history, and the restart hint.

### CLI / client
- `bio-pipeline env list` / `env install <spec>` / `env uninstall <name>` mirror the endpoints
  for headless use.

---

## 6. Data model changes

### Task (was `JobSpec`/`JobRecord`)
Add to `JobSpec` (`models.py:17`):
- `process_arg_mapping: dict[str, dict[str, str]]` (default `{}`)
- `parent_job_id: str | None`
- `stage: str | None`
- `matrix_key: dict[str, str]` (the variable bindings for this cell, e.g. `{run_tag, variant}`)
- `task_index: int` (ordinal within stage fan-out)
- `depends_on: list[str]` (upstream Task ids; populated as stages materialize)

`JobStore` (`storage.py`) gains the matching columns + a forward migration (the file already
does additive `ALTER TABLE` migrations, see `storage.py:44`). `input_sources` and
`process_arg_mapping` serialize as JSON like the existing `input_sources` column.

### Job (new parent table)
`id, name, definition (yaml/json), created_at, status, totals (counts)`. Status is **derived**
from child Tasks, not stored authoritatively (or cached and recomputed on read).

### Scheduling / dependency awareness
- `list_due_jobs` (`storage.py:156`) gains a guard: a Task is due only when all `depends_on`
  Tasks are `SUCCEEDED` (and none failed/cancelled). On upstream failure, dependents move to a
  `BLOCKED`/`SKIPPED` terminal state rather than running.
- New `JobStatus` value `BLOCKED` (and possibly `SKIPPED`). Add to the `StrEnum` at `models.py:9`.

---

## 7. Expansion engine (hybrid)

A new module `src/bio_pipeline_manager/job_definition.py`:

1. **Parse + validate** the Job Definition YAML (schema, unknown keys, undefined template vars,
   stage `needs:` cycles, referenced pipeline YAMLs exist).
2. **Expand matrix eagerly** at submit: cartesian product of `variables` → one cell per
   combination. Create the parent `Job` row and, for each cell, a *pending stage placeholder*.
3. **Expand fan-out lazily**: when a stage becomes eligible (its `needs:` are satisfied for that
   cell), read the fan-out source (`load_file_mapping` / patterns / `list_folders`), template
   each item, and materialize concrete Task rows. This is required because `collate`'s
   `folders_list` is produced by `preprocess` — the directory does not exist at submit time.
4. **Dry-run / preview**: same code path with a `materialize=False` flag returns the list of
   Tasks (resolved paths, inputs, args) **without** running them. Powers a "preview expansion"
   button/CLI before committing a large matrix.

The `JobQueue.run_due` (`job_queue.py:62`) calls the expander between drains so newly-eligible
stages materialize and flow into the existing claim/run machinery.

---

## 8. Surfaces (CLI / API / client / UI)

### CLI (`cli.py`)
- `bio-pipeline job submit <job_def.yaml>` — expand matrix, create Job + initial Tasks.
- `bio-pipeline job preview <job_def.yaml>` — dry-run; print the Task table.
- `bio-pipeline job status <job_id>` — rollup + per-stage/per-task breakdown.
- Keep `submit` (single Task) as a thin special case for ad-hoc runs.

### API (`backend/app/api/routes/jobs.py`)
- `POST /jobs` (single) stays. Add `POST /job-definitions` (submit), `GET /job-definitions/{id}`
  (tree: stages → tasks with rollup), `POST /job-definitions/preview`.
- Extend `JobResponse` / `schemas/pipelines.py` with `process_arg_mapping`, `parent_job_id`,
  `stage`, `matrix_key`.

### Notebook client (`client.py`) + types (`frontend/src/types/index.ts`)
- Mirror the new endpoints and the extended `Job` shape (`index.ts` `Job` interface).

### Frontend
- New **Job Definition** editor/validator (parallels the existing YAML store/validation flow,
  `README.md:22`), with a **preview-expansion** panel.
- Jobs page becomes **hierarchical**: Job → stage groups → tasks, with rollup status badges and
  per-task logs (reuse `JobExecutionPanel.tsx`).
- New **Environment** page for package management (install/list/uninstall + install log + audit
  history); see §5a.

---

## 9. Validation & safety

- **Definition validation** (before submit): schema shape, every `{var}`/`{item.field}` resolves,
  `needs:` form a DAG, referenced pipeline YAMLs + pipelines exist (reuse `yaml_validation.py`),
  fan-out sources resolvable (where checkable at submit time).
- **Expansion guardrails**: cap on total Tasks per Job (avoid an accidental 10k-Task matrix);
  preview shows the count before commit.
- **Path safety**: templated output dirs validated against an allowed root, consistent with the
  existing path-safety checks in the YAML store.

---

## 10. Phased rollout

1. **[DONE]** **In-process Task runner + params.** `python -m bio_pipeline_manager.run_task` runs
   the transferred `pipeline.engine.build_pipeline_from_yaml`. `process_arg_mapping` threaded
   through `JobSpec` → store → runner → API → CLI (`-p`) → client → types. **Unblocks collate.**
2. **[DONE]** **Package Management.** `bio_pipeline_manager/packages.py` (`PackageManager` +
   `InstallStore`) installs/uninstalls/lists via `sys.executable -m pip`, with an **audit log**
   (`installs.sqlite`), refusal while jobs are running (`JobStore.has_active_jobs`), and
   `importlib.invalidate_caches()` after each change. Backend `/api/v1/packages` (list/install/
   uninstall) gated by a bearer **admin token** (`PACKAGE_ADMIN_TOKEN`; 503 when unset, 401 on bad
   token). `bio-pipeline env list|install|uninstall` CLI and a frontend **Environment** page
   (token entry, install form, installed list, audit history, restart hint). Sources: pypi / git /
   editable / requirements.
3. **[DONE]** **Fan-out + matrix + stages + dependencies.** `job_definition.py` expands a Job
   Definition (`variables` matrix × ordered `stages` with `needs:` × `mapping_file`/`patterns`/
   `folders`/`none` fan-out) into materialized Tasks with `{token}` templating. `JobSpec` carries
   `parent_job_id`/`stage`/`matrix_key`/`depends_on`; `JobQueue.submit_definition` wires
   per-cell dependencies; dependency-aware `run_due` gates Tasks and moves failed-upstream Tasks
   to `BLOCKED`; `group_status` rollup. CLI `job preview`/`submit`/`status`. Replaces the two
   `.py` scripts **and** the `.bat` files; covers multi-YAML chaining. (Fan-out currently
   materialises eagerly at submit; lazy per-stage materialisation for filesystem-dependent
   fan-out, e.g. `folders` produced by an upstream stage, is still pending.)
4. **Surfaces.** **[API DONE]** Job Definition endpoints on both the backend
   (`/api/v1/job-definitions` preview/submit/list/detail) and the lightweight notebook server,
   plus `PipelineClient.{preview,submit,list,get}_definition`. **[UI DONE — unverified]** Frontend
   "Job Definitions" page (`/job-definitions`): YAML editor, Preview (expanded task list), Submit,
   Run-due, and a hierarchical group view (stages → per-cell tasks with rollup). `JobResponse`
   now exposes `stage`/`matrix_key`/`parent_job_id` for grouping. Frontend `type-check`/`vitest`
   could not be run in the dev sandbox (no Node runtime) — run `npm run type-check && npm run test`.
5. **Lazy stage materialisation.** Expand a stage's fan-out only when it becomes eligible (needed
   when a downstream `folders`/`patterns` source is produced by an upstream stage at run time).

---

## 11. Worked mapping: attached files → Job Definition

| Attached construct | New home |
|--------------------|----------|
| `.bat` `set RUN_TAG` loop | `variables.run_tag` |
| `.bat` three `--pipeline=` lines | `variables.variant[].pipeline` |
| `.bat` `H:\...\{RUN_TAG}\...` paths | `defaults.data_root` + `{run_tag}` templates |
| `preprocessing_pipeline.py` mapping loop | stage `preprocess`, `fanout.type: mapping_file` |
| per-file `output_dir = base/stem` | `output_dir: "{...}/{item.stem}"` |
| per-file `input_sources={raw_data,meta_data}` | stage `input_sources` with `{item.raw/meta}` |
| `collate` `input_sources={folders_list}` | stage `collate`, `fanout.type: none` |
| `collate` `process_arg_mapping` | stage `process_arg_mapping` |
| `.bat` preprocess-then-collate ordering | `collate.needs: [preprocess]` |
| scripts' success/fail results dict | Job rollup status + per-task records |
