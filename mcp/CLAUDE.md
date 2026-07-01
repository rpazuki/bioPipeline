# CLAUDE.md — Bio Pipeline Manager via MCP

You are operating the **Bio Pipeline Manager** through its MCP server
(`bio-pipeline-manager`). This file gives you the context to turn user requests
into the right tool calls. You are *not* editing the codebase here — you are
**driving a running system** over its API. For codebase work, read the repo-root
[CLAUDE.md](../CLAUDE.md) instead.

## What this system is

A local-first manager for **YAML-defined bioinformatics pipelines**. Admins
author and validate pipeline YAML, compose multi-stage **Job Definitions**, and
**publish** parameterised jobs. **Researchers** run those published jobs from a
catalog — supplying inputs, running them, downloading results, and scheduling
repeats. The actual scientific functions are external (`labUtils.*`), referenced
by name from the YAML.

## The entity model (know this before acting)

```
Pipeline YAML  ──defines──►  one or more named pipelines (processes + I/O)
      │
Job Definition ──composes──► multiple pipeline runs into staged, fanned-out Tasks
      │  (preview to expand → submit to queue as one parent "group")
      ▼
Job / Task     ──the queue──► individual runnable units with status + logs
      │
Published Job  ──wraps a Job Definition with researcher-facing FIELDS──►
      │  (draft → published → archived; only "published" is researcher-visible)
      ▼
Run            ──a researcher executing a published job with field VALUES──►
      │  produces a Task group + (optionally) a downloadable results artifact
Recurring Schedule / Recurring Job ──repeat a run / a plain job on an interval
```

- **Pipeline YAML** is the lowest layer; validate before saving.
- **Job Definition** expands into **Tasks** (fan-out / staged). *Preview first.*
- **Published Job** = a Job Definition + typed **fields** that researchers fill.
- **Run** = one execution of a published job with **values** for those fields.

## Your role depends on the logged-in account

The MCP server logs in with one configured account:

- **admin** → full surface: author/validate YAML, build & submit Job
  Definitions, manage the queue, author/publish/archive published jobs, manage
  users, type library, packages, and oversee all runs.
- **user (researcher)** → catalog only: browse published jobs, run them, manage
  your own runs and recurring schedules, manage your saved values.

If an admin tool returns a 403, the configured account is a researcher — say so
rather than retrying.

## Tool catalog (grouped)

**Connection** — `health`, `whoami`, `runtime_info`

**Pipeline YAMLs (admin)** — `list_pipeline_yamls`, `get_pipeline_yaml`,
`save_pipeline_yaml`, `delete_pipeline_yaml`, `validate_yaml`,
`validate_stored_yaml`, `list_pipeline_templates`, `get_pipeline_template`

**Jobs / queue (admin)** — `list_jobs`, `get_job`, `submit_job`, `get_job_logs`,
`cancel_job`, `delete_job`, `rewind_job`, `run_due_jobs`, `list_recurring_jobs`,
`create_recurring_job`, `stop_recurring_job`, `delete_recurring_job`

**Job Definitions (admin)** — `preview_job_definition`, `submit_job_definition`,
`list_job_groups`, `get_job_group`, `list_definitions`, `get_definition`,
`save_definition`, `delete_definition`, `list_definition_templates`,
`get_definition_template`

**Published jobs — admin** — `list_published_jobs_admin`,
`get_published_job_admin`, `inspect_published_job_definition`,
`create_published_job`, `update_published_job`, `publish_published_job`,
`archive_published_job`, `validate_published_job`, `delete_published_job`,
`list_admin_published_runs`

**Published jobs — researcher** — `list_published_jobs`, `get_published_job`,
`run_published_job`, `create_run_draft`, `list_my_runs`, `get_my_run`,
`cancel_my_run`, `rewind_my_run`, `delete_my_run`, `list_my_schedules`,
`create_recurring_schedule`, `stop_my_schedule`, `delete_my_schedule`

**Type library + saved values** — `list_types`, `get_type`, `upsert_type`,
`delete_type`, `extract_type`, `list_saved_values`, `delete_saved_value`

**Users + packages (admin)** — `list_users`, `create_user`, `update_user`,
`reset_user_password`, `list_packages`, `install_package`, `uninstall_package`,
`inspect_package`, `search_package_members`, `get_function_signature`

**Escape hatch** — `api_request(method, path, params, body)` for any endpoint
without a dedicated tool.

## Common workflows

**Run an existing published job (researcher):**
1. `list_published_jobs` → find the job id.
2. `get_published_job(id)` → read its `fields` (each has `id`, `type`,
   `required`, `io_role`). Map the user's intent to a `values` dict keyed by
   field `id`.
3. If any field is a file input (`io_role: "input"` with `upload` in `sources`),
   you need a workspace + uploaded bytes — see *File inputs* below.
4. `run_published_job(id, values=...)` → returns the run with its task group.
5. Poll `get_my_run(run_id)` for status; download results via the REST
   `my-runs/{run_id}/artifact` endpoint when `artifact_available` is true.

**Discover a process function (admin):** unsure which `labUtils.*` function or
class a pipeline should call, or what parameters it takes? `search_package_members`
by name (or `inspect_package("labUtils.…")` to list a module), then
`get_function_signature("labUtils.mod.fn")` to read its signature + docstring
before wiring it into a pipeline YAML.

**Author and publish a job (admin):**
1. Write/validate the pipeline YAML(s): `validate_yaml` → `save_pipeline_yaml`.
2. Compose a Job Definition; `preview_job_definition` to see the expanded tasks.
3. `inspect_published_job_definition(content)` → field candidates.
4. `create_published_job(name, definition_content, fields=...)` (starts `draft`).
5. `validate_published_job(id)`, then `publish_published_job(id)`.

**Submit a one-off / multi-task job (admin):**
- Single pipeline: `submit_job(yaml_name, pipeline_name, output_dir, ...)`.
- Multi-task: `preview_job_definition(content)` → `submit_job_definition(content)`
  → track with `get_job_group(parent_job_id)`.

## Gotchas

- **Preview before submitting** a Job Definition — fan-out can expand into many
  tasks, and downstream stages **materialize lazily** (preview may show some as
  `deferred`).
- **Validate before saving** pipeline YAML; the backend rejects an invalid doc
  (e.g. *"YAML must contain a non-empty 'pipelines' list"*) — surface that
  message, don't silently retry.
- **`values` keys are field ids**, not labels. Read them from
  `get_published_job`. A `required` field with no value fails the run.
- **File inputs** can't be streamed through an MCP tool. Use `create_run_draft`
  to get a `workspace_id`, upload bytes via the REST endpoint
  `POST /api/v1/published-jobs/catalog/{id}/runs/{workspace_id}/uploads/{field_id}`,
  then call `run_published_job` with `workspace_id` and matching `file_bindings`
  (`{field_id: {kind: "upload", path: "<handle>"}}`).
- **Timestamps** (`scheduled_at`, `ends_at`, `start_at`) are ISO-8601 strings.
- **Recurring** `unit` ∈ minutes|hours|days|weeks; `ends_mode` ∈ never|count|until.
- **Destructive / running actions** (`delete_*`, `submit_*`, `run_*`,
  `publish_*`, `install_package`, `reset_user_password`) change real state —
  confirm with the user before firing them.
- **Background workers** normally run due jobs automatically; only call
  `run_due_jobs` to force a tick (e.g. when the worker is disabled).
