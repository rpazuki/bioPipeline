"""FastMCP server exposing the Bio Pipeline Manager API as MCP tools.

Grouped by subsystem, mirroring the backend routers under ``/api/v1``:

* connection / health / runtime
* pipeline YAMLs + validation + templates   (admin)
* jobs / queue / recurring admin jobs         (admin)
* job definitions (multi-task) + store        (admin)
* published jobs — admin authoring            (admin)
* published jobs — researcher catalog & runs  (any authenticated user)
* recurring schedules (researcher)
* type library + saved typed values
* users + packages                            (admin)
* generic escape hatch (``api_request``)

Tool docstrings are the descriptions the model sees — keep them action-oriented.
Permissions are enforced server-side by role; logging in as an admin exposes the
whole surface, a ``user`` (researcher) only the catalog/run/saved-value tools.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import BioPipelineClient

mcp = FastMCP("bio-pipeline-manager")

_client: BioPipelineClient | None = None


def client() -> BioPipelineClient:
    global _client
    if _client is None:
        _client = BioPipelineClient()
    return _client


# ======================================================================= #
# Connection / health / runtime
# ======================================================================= #
@mcp.tool()
def health() -> Any:
    """Check the backend is reachable. Returns ``{status, app}``. No auth needed."""
    return client().health()


@mcp.tool()
def whoami() -> Any:
    """Return the currently authenticated user (id, username, role, is_active)."""
    return client().get("/auth/me")


@mcp.tool()
def runtime_info() -> Any:
    """Inspect the server runtime: pipeline home, YAML root, YAML files, cwd. (admin)"""
    return client().get("/runtime")


# ======================================================================= #
# Pipeline YAMLs / validation / templates  (admin)
# ======================================================================= #
@mcp.tool()
def list_pipeline_yamls() -> Any:
    """List all stored pipeline YAML files with the pipelines each defines. (admin)"""
    return client().get("/pipeline-yamls")


@mcp.tool()
def get_pipeline_yaml(name: str) -> Any:
    """Read one stored pipeline YAML (content + pipeline names + validity). (admin)

    ``name`` is the store-relative path, e.g. ``folder/my_pipeline.yaml``.
    """
    return client().get(f"/pipeline-yamls/{name}")


@mcp.tool()
def save_pipeline_yaml(name: str, content: str, overwrite: bool = True) -> Any:
    """Create or update a pipeline YAML file. (admin)

    ``name`` is the store-relative path; ``content`` is the raw YAML. Set
    ``overwrite=False`` to fail if the file already exists.
    """
    return client().post(
        "/pipeline-yamls",
        json={"name": name, "content": content, "overwrite": overwrite},
    )


@mcp.tool()
def delete_pipeline_yaml(name: str) -> Any:
    """Delete a stored pipeline YAML file by store-relative path. (admin)"""
    return client().delete(f"/pipeline-yamls/{name}")


@mcp.tool()
def validate_yaml(content: str, imports: bool = False) -> Any:
    """Validate raw pipeline YAML content without saving it. (admin)

    Set ``imports=True`` to also resolve/validate the labUtils import targets.
    Returns ``{is_valid, issues, pipelines}``.
    """
    return client().post("/validation/yaml", json={"content": content, "imports": imports})


@mcp.tool()
def validate_stored_yaml(name: str, imports: bool = False) -> Any:
    """Validate an already-stored pipeline YAML by store-relative path. (admin)"""
    return client().get(f"/validation/pipeline-yamls/{name}", params={"imports": imports})


@mcp.tool()
def list_pipeline_templates() -> Any:
    """List built-in starter pipeline-YAML templates (name + description). (admin)"""
    return client().get("/templates")


@mcp.tool()
def get_pipeline_template(template_name: str) -> Any:
    """Get one pipeline-YAML template's full content. (admin)"""
    return client().get(f"/templates/{template_name}")


# ======================================================================= #
# Jobs / queue / recurring admin jobs  (admin)
# ======================================================================= #
@mcp.tool()
def list_jobs() -> Any:
    """List every job/task in the queue with status and timing. (admin)"""
    return client().get("/jobs")


@mcp.tool()
def get_job(job_id: str) -> Any:
    """Get one job/task by id. (admin)"""
    return client().get(f"/jobs/{job_id}")


@mcp.tool()
def submit_job(
    yaml_name: str,
    pipeline_name: str,
    output_dir: str,
    input_sources: dict[str, str] | None = None,
    input_arg_mapping: dict[str, dict[str, Any]] | None = None,
    process_arg_mapping: dict[str, dict[str, Any]] | None = None,
    output_path_mapping: dict[str, Any] | None = None,
    backend: str = "local",
    scheduled_at: str | None = None,
) -> Any:
    """Submit a single pipeline run to the queue. (admin)

    ``yaml_name`` is a stored pipeline YAML; ``pipeline_name`` is one pipeline
    inside it; ``output_dir`` is where artifacts are written. ``scheduled_at`` is
    an ISO-8601 timestamp to defer execution (omit to run as soon as picked up).
    Mappings override per-process/input args. Returns the created job record.
    """
    return client().post(
        "/jobs",
        json={
            "yaml_name": yaml_name,
            "pipeline_name": pipeline_name,
            "output_dir": output_dir,
            "input_sources": input_sources or {},
            "input_arg_mapping": input_arg_mapping or {},
            "process_arg_mapping": process_arg_mapping or {},
            "output_path_mapping": output_path_mapping or {},
            "backend": backend,
            "scheduled_at": scheduled_at,
        },
    )


@mcp.tool()
def get_job_logs(job_id: str) -> Any:
    """Fetch the captured stdout/stderr log for a job/task. (admin)"""
    return client().get(f"/jobs/{job_id}/logs")


@mcp.tool()
def cancel_job(job_id: str) -> Any:
    """Cancel a queued or running job/task. (admin)"""
    return client().post(f"/jobs/{job_id}/cancel")


@mcp.tool()
def delete_job(job_id: str) -> Any:
    """Delete a job/task record from the queue. (admin)"""
    return client().delete(f"/jobs/{job_id}")


@mcp.tool()
def rewind_job(job_id: str, scheduled_at: str | None = None) -> Any:
    """Re-queue a finished job to run again, optionally at ``scheduled_at``. (admin)"""
    body = {"scheduled_at": scheduled_at} if scheduled_at else None
    return client().post(f"/jobs/{job_id}/rewind", json=body)


@mcp.tool()
def run_due_jobs(parallel: int = 1) -> Any:
    """Run all jobs whose scheduled time has arrived, ``parallel`` at a time. (admin)

    Normally a background worker does this automatically; call it to force a tick.
    """
    return client().post("/jobs/run-due", params={"parallel": parallel})


@mcp.tool()
def list_recurring_jobs() -> Any:
    """List admin recurring-job schedules (repeat a plain job on an interval). (admin)"""
    return client().get("/jobs/schedules")


@mcp.tool()
def create_recurring_job(
    yaml_name: str,
    pipeline_name: str,
    output_dir: str,
    every_n: int = 1,
    unit: str = "days",
    ends_mode: str = "never",
    ends_count: int = 0,
    ends_at: str | None = None,
    start_at: str | None = None,
    input_sources: dict[str, str] | None = None,
    process_arg_mapping: dict[str, dict[str, Any]] | None = None,
    backend: str = "local",
) -> Any:
    """Schedule a plain job to repeat every ``every_n`` ``unit``. (admin)

    ``unit`` ∈ minutes|hours|days|weeks. ``ends_mode`` ∈ never|count|until (with
    ``ends_count`` or ``ends_at``). ``start_at`` is the first occurrence (ISO-8601).
    """
    job = {
        "yaml_name": yaml_name,
        "pipeline_name": pipeline_name,
        "output_dir": output_dir,
        "input_sources": input_sources or {},
        "process_arg_mapping": process_arg_mapping or {},
        "backend": backend,
    }
    return client().post(
        "/jobs/schedules",
        json={
            "job": job,
            "every_n": every_n,
            "unit": unit,
            "ends_mode": ends_mode,
            "ends_count": ends_count,
            "ends_at": ends_at,
            "start_at": start_at,
        },
    )


@mcp.tool()
def stop_recurring_job(schedule_id: str) -> Any:
    """Deactivate an admin recurring-job schedule (keeps the record). (admin)"""
    return client().post(f"/jobs/schedules/{schedule_id}/stop")


@mcp.tool()
def delete_recurring_job(schedule_id: str) -> Any:
    """Delete an admin recurring-job schedule. (admin)"""
    return client().delete(f"/jobs/schedules/{schedule_id}")


# ======================================================================= #
# Job Definitions (multi-task) + store  (admin)
# ======================================================================= #
@mcp.tool()
def preview_job_definition(content: str) -> Any:
    """Expand a multi-task Job Definition into its tasks without queueing. (admin)

    ``content`` is the Job Definition YAML. Returns the materialized task list and
    any fan-out warnings — use this to dry-run before ``submit_job_definition``.
    """
    return client().post("/job-definitions/preview", json={"content": content})


@mcp.tool()
def submit_job_definition(content: str, scheduled_at: str | None = None) -> Any:
    """Expand and queue a multi-task Job Definition as one parent group. (admin)

    Returns the job group (parent id + per-task records). ``scheduled_at`` defers it.
    """
    return client().post(
        "/job-definitions", json={"content": content, "scheduled_at": scheduled_at}
    )


@mcp.tool()
def list_job_groups() -> Any:
    """List submitted Job Definition groups with rolled-up status/counts. (admin)"""
    return client().get("/job-definitions")


@mcp.tool()
def get_job_group(parent_job_id: str) -> Any:
    """Get one Job Definition group's detail incl. every task. (admin)"""
    return client().get(f"/job-definitions/{parent_job_id}")


@mcp.tool()
def list_definitions() -> Any:
    """List saved Job Definition documents in the store. (admin)"""
    return client().get("/job-definition-store")


@mcp.tool()
def get_definition(name: str) -> Any:
    """Read a saved Job Definition document by store-relative name. (admin)"""
    return client().get(f"/job-definition-store/{name}")


@mcp.tool()
def save_definition(name: str, content: str, overwrite: bool = True) -> Any:
    """Create or update a saved Job Definition document. (admin)"""
    return client().post(
        "/job-definition-store",
        json={"name": name, "content": content, "overwrite": overwrite},
    )


@mcp.tool()
def delete_definition(name: str) -> Any:
    """Delete a saved Job Definition document by store-relative name. (admin)"""
    return client().delete(f"/job-definition-store/{name}")


@mcp.tool()
def list_definition_templates() -> Any:
    """List built-in Job Definition templates (name + description). (admin)"""
    return client().get("/job-definition-templates")


@mcp.tool()
def get_definition_template(template_name: str) -> Any:
    """Get one Job Definition template's full content. (admin)"""
    return client().get(f"/job-definition-templates/{template_name}")


# ======================================================================= #
# Published jobs — admin authoring
# ======================================================================= #
@mcp.tool()
def list_published_jobs_admin() -> Any:
    """List all published jobs incl. drafts/archived (admin authoring view). (admin)"""
    return client().get("/published-jobs/admin")


@mcp.tool()
def get_published_job_admin(published_job_id: str) -> Any:
    """Get a published job's full admin record (definition + fields). (admin)"""
    return client().get(f"/published-jobs/admin/{published_job_id}")


@mcp.tool()
def inspect_published_job_definition(content: str) -> Any:
    """Analyze a Job Definition and suggest researcher-facing field candidates. (admin)

    Use before authoring a published job to discover bindable inputs/params.
    """
    return client().post("/published-jobs/admin/inspect", json={"content": content})


@mcp.tool()
def create_published_job(
    name: str,
    definition_content: str,
    fields: list[dict[str, Any]],
    description: str = "",
    definition_name: str = "",
    status: str = "draft",
) -> Any:
    """Create a published job (researcher-facing parameterised job). (admin)

    ``definition_content`` is the underlying Job Definition YAML; ``fields`` is the
    list of researcher field specs (use ``inspect_published_job_definition`` to
    derive candidates). ``status`` ∈ draft|published|archived.
    """
    return client().post(
        "/published-jobs/admin",
        json={
            "name": name,
            "description": description,
            "definition_name": definition_name,
            "definition_content": definition_content,
            "fields": fields,
            "status": status,
        },
    )


@mcp.tool()
def update_published_job(
    published_job_id: str,
    name: str | None = None,
    description: str | None = None,
    definition_name: str | None = None,
    definition_content: str | None = None,
    fields: list[dict[str, Any]] | None = None,
) -> Any:
    """Update a published job. Only the provided fields change. (admin)"""
    body = {
        "name": name,
        "description": description,
        "definition_name": definition_name,
        "definition_content": definition_content,
        "fields": fields,
    }
    return client().patch(f"/published-jobs/admin/{published_job_id}", json=body)


@mcp.tool()
def publish_published_job(published_job_id: str) -> Any:
    """Mark a published job as ``published`` so researchers can run it. (admin)"""
    return client().post(f"/published-jobs/admin/{published_job_id}/publish")


@mcp.tool()
def archive_published_job(published_job_id: str) -> Any:
    """Archive a published job (removes it from the researcher catalog). (admin)"""
    return client().post(f"/published-jobs/admin/{published_job_id}/archive")


@mcp.tool()
def validate_published_job(published_job_id: str) -> Any:
    """Validate a published job's definition + fields; reports run count. (admin)"""
    return client().post(f"/published-jobs/admin/{published_job_id}/validate")


@mcp.tool()
def delete_published_job(published_job_id: str, force: bool = False) -> Any:
    """Delete a published job. ``force=True`` to delete one that has runs. (admin)"""
    return client().delete(
        f"/published-jobs/admin/{published_job_id}", params={"force": force}
    )


@mcp.tool()
def list_admin_published_runs() -> Any:
    """List every researcher run across all published jobs (admin oversight). (admin)"""
    return client().get("/published-jobs/admin/runs")


# ======================================================================= #
# Published jobs — researcher catalog & runs
# ======================================================================= #
@mcp.tool()
def list_published_jobs() -> Any:
    """List the published-job catalog visible to researchers (status=published)."""
    return client().get("/published-jobs")


@mcp.tool()
def get_published_job(published_job_id: str) -> Any:
    """Get a catalog published job's public detail (fields a researcher fills in)."""
    return client().get(f"/published-jobs/catalog/{published_job_id}")


@mcp.tool()
def run_published_job(
    published_job_id: str,
    values: dict[str, Any] | None = None,
    scheduled_at: str | None = None,
    workspace_id: str | None = None,
    file_bindings: dict[str, dict[str, Any]] | None = None,
) -> Any:
    """Run a published job by supplying its field ``values``.

    ``values`` maps field id → value. ``scheduled_at`` (ISO-8601) defers the run.
    For jobs with uploaded-file inputs, create a workspace + upload first (see
    ``create_run_draft``) and pass ``workspace_id`` plus ``file_bindings``
    (field id → {kind, path, root}). Returns the created run with task group + logs.
    """
    return client().post(
        f"/published-jobs/catalog/{published_job_id}/runs",
        json={
            "values": values or {},
            "scheduled_at": scheduled_at,
            "workspace_id": workspace_id,
            "file_bindings": file_bindings or {},
        },
    )


@mcp.tool()
def create_run_draft(published_job_id: str) -> Any:
    """Reserve a per-run workspace for uploads before running a file-input job.

    Returns ``{workspace_id}``. Upload bytes via the HTTP API, then pass the id to
    ``run_published_job`` with matching ``file_bindings`` (binary upload itself is
    not exposed as an MCP tool — use the REST endpoint for raw file streaming).
    """
    return client().post(f"/published-jobs/catalog/{published_job_id}/runs/draft")


@mcp.tool()
def list_my_runs() -> Any:
    """List the current user's own published-job runs with status/counts."""
    return client().get("/published-jobs/my-runs")


@mcp.tool()
def get_my_run(run_id: str) -> Any:
    """Get one of the current user's runs in full detail (task group + logs)."""
    return client().get(f"/published-jobs/my-runs/{run_id}")


@mcp.tool()
def cancel_my_run(run_id: str) -> Any:
    """Cancel the queued/running tasks of one of the current user's runs."""
    return client().post(f"/published-jobs/my-runs/{run_id}/cancel")


@mcp.tool()
def rewind_my_run(run_id: str, scheduled_at: str | None = None) -> Any:
    """Re-run one of the current user's runs now, or deferred to ``scheduled_at``."""
    body = {"scheduled_at": scheduled_at} if scheduled_at else None
    return client().post(f"/published-jobs/my-runs/{run_id}/rewind", json=body)


@mcp.tool()
def delete_my_run(run_id: str) -> Any:
    """Delete one of the current user's runs (cancels tasks, drops workspace)."""
    return client().delete(f"/published-jobs/my-runs/{run_id}")


# -- recurring schedules (researcher) -------------------------------------- #
@mcp.tool()
def list_my_schedules() -> Any:
    """List the current user's recurring published-job schedules."""
    return client().get("/published-jobs/my-schedules")


@mcp.tool()
def create_recurring_schedule(
    published_job_id: str,
    values: dict[str, Any] | None = None,
    every_n: int = 1,
    unit: str = "days",
    ends_mode: str = "never",
    ends_count: int = 0,
    ends_at: str | None = None,
    start_at: str | None = None,
    workspace_id: str | None = None,
    file_bindings: dict[str, dict[str, Any]] | None = None,
) -> Any:
    """Schedule a published job to run every ``every_n`` ``unit`` for the current user.

    ``unit`` ∈ minutes|hours|days|weeks. ``ends_mode`` ∈ never|count|until. The
    schedule is dry-run validated at creation, so a never-runnable one is rejected.
    """
    return client().post(
        f"/published-jobs/catalog/{published_job_id}/schedules",
        json={
            "values": values or {},
            "file_bindings": file_bindings or {},
            "workspace_id": workspace_id,
            "every_n": every_n,
            "unit": unit,
            "ends_mode": ends_mode,
            "ends_count": ends_count,
            "ends_at": ends_at,
            "start_at": start_at,
        },
    )


@mcp.tool()
def stop_my_schedule(schedule_id: str) -> Any:
    """Deactivate one of the current user's recurring schedules."""
    return client().post(f"/published-jobs/my-schedules/{schedule_id}/stop")


@mcp.tool()
def delete_my_schedule(schedule_id: str) -> Any:
    """Delete one of the current user's recurring schedules."""
    return client().delete(f"/published-jobs/my-schedules/{schedule_id}")


# ======================================================================= #
# Type library (admin) + saved typed values (researcher)
# ======================================================================= #
@mcp.tool()
def list_types() -> Any:
    """List the project type library (structured types for typed fields). (admin)"""
    return client().get("/type-library")


@mcp.tool()
def get_type(name: str) -> Any:
    """Get one type definition from the type library by name. (admin)"""
    return client().get(f"/type-library/{name}")


@mcp.tool()
def upsert_type(
    name: str,
    description: str = "",
    fields: dict[str, dict[str, Any]] | None = None,
    type: str = "",
    options: list[Any] | None = None,
    default: Any = None,
) -> Any:
    """Create or replace a type in the library. (admin)

    A *compound* type passes ``fields`` (name → spec). A *simple/scalar* type
    instead passes a primitive ``type`` (+ optional enum ``options`` / ``default``).
    """
    return client().put(
        f"/type-library/{name}",
        json={
            "description": description,
            "fields": fields or {},
            "type": type,
            "options": options or [],
            "default": default,
        },
    )


@mcp.tool()
def delete_type(name: str) -> Any:
    """Delete a type from the library by name. (admin)"""
    return client().delete(f"/type-library/{name}")


@mcp.tool()
def extract_type(qualified_name: str) -> Any:
    """Introspect a Python class (``module.Class``) into library type entries. (admin)"""
    return client().post("/type-library/extract", json={"qualified_name": qualified_name})


@mcp.tool()
def list_saved_values() -> Any:
    """List the current user's saved reusable typed/plain field values."""
    return client().get("/saved-typed-values")


@mcp.tool()
def delete_saved_value(record_id: str) -> Any:
    """Delete one of the current user's saved values by id."""
    return client().delete(f"/saved-typed-values/{record_id}")


# ======================================================================= #
# Users + packages  (admin)
# ======================================================================= #
@mcp.tool()
def list_users() -> Any:
    """List all user accounts (researchers + admins). (admin)"""
    return client().get("/users")


@mcp.tool()
def create_user(
    username: str,
    password: str,
    role: str = "user",
    display_name: str = "",
    is_active: bool = True,
) -> Any:
    """Create a user account. ``role`` ∈ user|admin. (admin)"""
    return client().post(
        "/users",
        json={
            "username": username,
            "password": password,
            "role": role,
            "display_name": display_name,
            "is_active": is_active,
        },
    )


@mcp.tool()
def update_user(
    user_id: str,
    username: str | None = None,
    display_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> Any:
    """Update a user account. Only the provided fields change. (admin)"""
    return client().patch(
        f"/users/{user_id}",
        json={
            "username": username,
            "display_name": display_name,
            "role": role,
            "is_active": is_active,
        },
    )


@mcp.tool()
def reset_user_password(user_id: str, password: str) -> Any:
    """Reset a user's password to the given value. (admin)"""
    return client().post(f"/users/{user_id}/reset-password", json={"password": password})


@mcp.tool()
def list_packages() -> Any:
    """List installed scientific packages + install/uninstall history. (admin)"""
    return client().get("/packages")


@mcp.tool()
def install_package(spec: str, source_type: str = "pypi") -> Any:
    """Install a package into the runtime env. ``source_type`` ∈ pypi|git|... (admin)"""
    return client().post("/packages/install", json={"spec": spec, "source_type": source_type})


@mcp.tool()
def uninstall_package(name: str) -> Any:
    """Uninstall a package from the runtime environment by name. (admin)"""
    return client().post("/packages/uninstall", json={"name": name})


# ======================================================================= #
# Generic escape hatch
# ======================================================================= #
@mcp.tool()
def api_request(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    body: Any | None = None,
) -> Any:
    """Call any backend API endpoint not covered by a dedicated tool.

    ``method`` ∈ GET|POST|PATCH|PUT|DELETE. ``path`` is relative to the API root,
    e.g. ``/jobs`` or ``/published-jobs/admin``. Use the dedicated tools when one
    exists; this is the fallback for raw access.
    """
    return client().request(method.upper(), path, params=params, json=body)


def main() -> None:
    """Console entry point — runs the server over stdio (Claude Desktop transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
