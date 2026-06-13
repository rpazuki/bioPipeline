from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from bio_pipeline_manager.job_definition import (
    PROVIDED_LATER,
    JobDefinitionError,
    contains_provided_later,
    parse_job_definition,
)
from bio_pipeline_manager.models import utc_now
from bio_pipeline_manager.run_workspace import RunWorkspaceError, RunWorkspaceStore
from bio_pipeline_manager.shared_storage import SharedStorage, SharedStorageError
from bio_pipeline_manager.type_schema import (
    CONTAINERS,
    TypeSchemaError,
    coerce_typed_value,
    resolve_type,
    suggest_type,
    validate_library,
)

FIELD_TYPES = {
    "string",
    "text",
    "integer",
    "float",
    "boolean",
    "enum",
    "multi_enum",
    "path",
    "file",
    "directory",
    "glob",
    "datetime",
    "list",
    "object",
    "json",
    # A structured value bound to a named type from the project type library. The
    # resolved structure travels on the field as ``type_schema`` (+ ``schema_ref`` /
    # ``container``), so run time never needs the library.
    "typed",
}


@dataclass(frozen=True)
class PublishedJobRecord:
    id: str
    name: str
    description: str
    status: str
    version: int
    definition_name: str
    definition_content: str
    fields: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    created_by: str
    updated_by: str


@dataclass(frozen=True)
class PublishedRunRecord:
    id: str
    published_job_id: str
    published_version: int
    user_id: str
    values: dict[str, Any]
    rendered_definition: str
    parent_job_id: str
    created_at: datetime
    workspace_id: str = ""
    file_bindings: dict[str, Any] = field(default_factory=dict)


class PublishedJobError(ValueError):
    pass


class PublishedJobStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS published_jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    definition_name TEXT NOT NULL DEFAULT '',
                    definition_content TEXT NOT NULL,
                    fields TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    published_at TEXT,
                    created_by TEXT NOT NULL DEFAULT '',
                    updated_by TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS published_runs (
                    id TEXT PRIMARY KEY,
                    published_job_id TEXT NOT NULL,
                    published_version INTEGER NOT NULL,
                    user_id TEXT NOT NULL,
                    field_values TEXT NOT NULL DEFAULT '{}',
                    rendered_definition TEXT NOT NULL,
                    parent_job_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT '',
                    file_bindings TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            # Additive migration for databases created before the workspace columns.
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(published_runs)")}
            if "workspace_id" not in existing:
                conn.execute("ALTER TABLE published_runs ADD COLUMN workspace_id TEXT NOT NULL DEFAULT ''")
            if "file_bindings" not in existing:
                conn.execute("ALTER TABLE published_runs ADD COLUMN file_bindings TEXT NOT NULL DEFAULT '{}'")

    def create(
        self,
        *,
        name: str,
        description: str,
        definition_name: str,
        definition_content: str,
        fields: list[dict[str, Any]],
        actor: str,
        status: str = "draft",
    ) -> PublishedJobRecord:
        _validate_definition_and_fields(definition_content, fields)
        record_id = uuid.uuid4().hex
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO published_jobs (
                    id, name, description, status, version, definition_name,
                    definition_content, fields, created_at, updated_at,
                    published_at, created_by, updated_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    name,
                    description,
                    status,
                    1,
                    definition_name,
                    definition_content,
                    json.dumps(fields, sort_keys=True),
                    now.isoformat(),
                    now.isoformat(),
                    now.isoformat() if status == "published" else None,
                    actor,
                    actor,
                ),
            )
        return self.get(record_id)

    def update(
        self,
        record_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        definition_name: str | None = None,
        definition_content: str | None = None,
        fields: list[dict[str, Any]] | None = None,
        actor: str,
    ) -> PublishedJobRecord:
        current = self.get(record_id)
        next_content = definition_content if definition_content is not None else current.definition_content
        next_fields = fields if fields is not None else current.fields
        _validate_definition_and_fields(next_content, next_fields)
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE published_jobs
                SET name = ?,
                    description = ?,
                    definition_name = ?,
                    definition_content = ?,
                    fields = ?,
                    version = version + 1,
                    updated_at = ?,
                    updated_by = ?
                WHERE id = ?
                """,
                (
                    name if name is not None else current.name,
                    description if description is not None else current.description,
                    definition_name if definition_name is not None else current.definition_name,
                    next_content,
                    json.dumps(next_fields, sort_keys=True),
                    utc_now().isoformat(),
                    actor,
                    record_id,
                ),
            )
        return self.get(record_id)

    def set_status(self, record_id: str, status: str, *, actor: str) -> PublishedJobRecord:
        if status not in {"draft", "published", "archived"}:
            raise PublishedJobError(f"Unknown published job status: {status}")
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE published_jobs
                SET status = ?,
                    updated_at = ?,
                    updated_by = ?,
                    published_at = CASE WHEN ? = 'published' THEN ? ELSE published_at END
                WHERE id = ?
                """,
                (status, utc_now().isoformat(), actor, status, utc_now().isoformat(), record_id),
            )
        return self.get(record_id)

    def get(self, record_id: str) -> PublishedJobRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM published_jobs WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(f"Published job not found: {record_id}")
        return _published_job_from_row(row)

    def delete(self, record_id: str, *, force: bool = False) -> None:
        self.get(record_id)
        run_count = self.run_count(record_id)
        if run_count and not force:
            raise PublishedJobError("Published job has runs; archive it or delete with force")
        with self.connect() as conn:
            if force:
                conn.execute("DELETE FROM published_runs WHERE published_job_id = ?", (record_id,))
            conn.execute("DELETE FROM published_jobs WHERE id = ?", (record_id,))

    def run_count(self, record_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM published_runs WHERE published_job_id = ?",
                (record_id,),
            ).fetchone()
        return int(row["count"]) if row else 0

    def list(self, *, status: str | None = None) -> list[PublishedJobRecord]:
        query = "SELECT * FROM published_jobs"
        params: tuple[Any, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY updated_at DESC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_published_job_from_row(row) for row in rows]

    def create_run(
        self,
        *,
        published_job_id: str,
        published_version: int,
        user_id: str,
        values: dict[str, Any],
        rendered_definition: str,
        parent_job_id: str,
        workspace_id: str = "",
        file_bindings: dict[str, Any] | None = None,
    ) -> PublishedRunRecord:
        run_id = uuid.uuid4().hex
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO published_runs (
                    id, published_job_id, published_version, user_id, field_values,
                    rendered_definition, parent_job_id, created_at, workspace_id, file_bindings
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    published_job_id,
                    published_version,
                    user_id,
                    json.dumps(values, sort_keys=True),
                    rendered_definition,
                    parent_job_id,
                    now.isoformat(),
                    workspace_id,
                    json.dumps(file_bindings or {}, sort_keys=True),
                ),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> PublishedRunRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM published_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"Published run not found: {run_id}")
        return _published_run_from_row(row)

    def delete_run(self, run_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM published_runs WHERE id = ?", (run_id,))

    def get_run_by_parent(self, parent_job_id: str) -> PublishedRunRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM published_runs WHERE parent_job_id = ?", (parent_job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Published run not found for parent job: {parent_job_id}")
        return _published_run_from_row(row)

    def list_runs(
        self,
        *,
        user_id: str | None = None,
        published_job_id: str | None = None,
    ) -> list[PublishedRunRecord]:
        query = "SELECT * FROM published_runs"
        filters = []
        params: list[Any] = []
        if user_id is not None:
            filters.append("user_id = ?")
            params.append(user_id)
        if published_job_id is not None:
            filters.append("published_job_id = ?")
            params.append(published_job_id)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY created_at DESC"
        with self.connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [_published_run_from_row(row) for row in rows]


def inspect_definition(
    definition_content: str,
    *,
    yaml_loader: Callable[[str], str] | None = None,
    type_library: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    job_def = parse_job_definition(definition_content)
    raw = yaml.safe_load(definition_content) or {}
    # Inline type definitions declared directly in the job YAML under definitions:.
    # These are structurally identical to the project type library and take priority
    # over library suggestions when a candidate's value matches.
    inline_defs: dict[str, Any] = raw.get("definitions") or {}
    if inline_defs:
        try:
            validate_library(inline_defs)
        except TypeSchemaError as exc:
            raise ValueError(f"Job 'definitions:' block is invalid: {exc}") from exc
    candidates: list[dict[str, Any]] = []

    for name, values in job_def.variables.items():
        options = [_option_for_value(value) for value in values]
        default = values[0] if values else None
        candidates.append(
            _candidate(
                f"var_{name}",
                f"Variable: {name}",
                "enum" if options else "string",
                f"Selects the {name} value used when this job expands.",
                default,
                [{"target": "definition_path", "path": ["variables", name]}],
                options=options,
                example=options[0]["label"] if options else str(default or ""),
            )
        )

    for name, value in job_def.defaults.items():
        candidates.append(
            _candidate(
                f"default_{name}",
                f"Default: {name}",
                _infer_field_type(value),
                f"Sets the shared default value {name} before stages are rendered.",
                value,
                [{"target": "definition_path", "path": ["defaults", name]}],
                example=str(value),
            )
        )

    stages_by_name = {stage["name"]: stage for stage in job_def.stages}
    for stage_name, stage in stages_by_name.items():
        candidates.extend(_stage_candidates(stage_name, stage))
        if yaml_loader and "{" not in str(stage.get("pipeline_yaml", "")) and "{" not in str(stage.get("pipeline", "")):
            candidates.extend(_pipeline_candidates(stage_name, stage, yaml_loader))

    deduped = _dedupe_candidates(candidates)
    for candidate in deduped:
        role, accept = _io_defaults(candidate["type"], candidate.get("bindings", []))
        candidate["io_role"] = role
        candidate["accept"] = accept
        candidate["sources"] = ["upload"] if role == "input" else []
        candidate["delivery"] = ["download"] if role == "output" else []
        candidate["shared_roots"] = []
        # Inline definitions: the job itself declared the type, so auto-bind — no
        # admin choice needed. Takes priority over the project library suggestion.
        if inline_defs:
            suggestion = suggest_type(inline_defs, candidate.get("default"))
            if suggestion:
                stype, scontainer = suggestion
                try:
                    candidate["type"] = "typed"
                    candidate["container"] = scontainer
                    candidate["type_schema"] = resolve_type(inline_defs, stype)
                except TypeSchemaError:
                    pass
        # Library suggestion: non-binding hint shown to the admin (only when the
        # candidate was not already resolved from an inline definitions: block).
        if type_library and candidate.get("type") != "typed":
            suggestion = suggest_type(type_library, candidate.get("default"))
            if suggestion:
                candidate["schema_suggestion"], candidate["schema_suggestion_container"] = suggestion
    return deduped


def _is_stage_output_dir_binding(binding: dict[str, Any]) -> bool:
    """True if a binding targets a stage's ``output_dir`` in the definition."""
    path = binding.get("path") or []
    return (
        binding.get("target") == "definition_path"
        and isinstance(path, list)
        and len(path) == 3
        and path[0] == "stages"
        and path[2] == "output_dir"
    )


def _stage_output_template_and_fanout(definition_content: str, stage_name: str) -> tuple[str, str]:
    """Return ``(output_dir_template, fanout_type)`` for a stage, else ``("", "none")``."""
    try:
        data = yaml.safe_load(definition_content)
    except yaml.YAMLError:
        return "", "none"
    if not isinstance(data, dict):
        return "", "none"
    for stage in data.get("stages", []) or []:
        if isinstance(stage, dict) and stage.get("name") == stage_name:
            template = str(stage.get("output_dir", "") or "")
            fanout = stage.get("fanout") or {"type": "none"}
            ftype = (fanout.get("type") if isinstance(fanout, dict) else "none") or "none"
            return template, ftype
    return "", "none"


def _reroot_output_under_workspace(template: str, workspace_dir: str) -> str:
    """Re-root a stage ``output_dir`` template under the run workspace.

    A fanned-out stage's ``output_dir`` varies per item (e.g.
    ``{data_root}\\processed\\{variant.name}\\{item.stem}``). Replacing it with a
    single workspace directory would make every fan-out Task write to — and
    overwrite — the same place. Instead we keep the per-cell / per-item structure
    but place it UNDER the workspace dir: the leading root segment (e.g.
    ``{data_root}``) is dropped and the remaining token-bearing tail is appended
    to the workspace dir, so each Task still gets a distinct folder and the
    outputs are collected from the workspace for delivery.
    """
    segments = [seg for seg in re.split(r"[\\/]+", template.strip()) if seg]
    tail = segments[1:]  # drop the original root segment (replaced by the workspace)
    if not tail:
        return workspace_dir
    return os.path.join(workspace_dir, *tail)


def resolve_io(
    record: PublishedJobRecord,
    values: dict[str, Any],
    *,
    file_bindings: dict[str, Any] | None = None,
    workspaces: RunWorkspaceStore | None = None,
    workspace_id: str | None = None,
    shared: SharedStorage | None = None,
) -> dict[str, Any]:
    """Rewrite researcher input/output field values to concrete paths.

    Returns a new values dict where each ``io_role: input`` field points at its
    uploaded (or, later, shared) source and each ``io_role: output`` field
    points at a per-run workspace output directory. Fields with
    ``io_role: none`` pass through unchanged (today's behavior). The result is
    fed to :func:`render_definition`, so substitution happens before matrix/
    stage expansion and every fan-out Task of the run shares one workspace root.
    """
    file_bindings = file_bindings or {}
    resolved = dict(values)
    for field_def in record.fields:
        role = field_def.get("io_role", "none")
        if role not in {"input", "output"}:
            continue
        field_id = field_def["id"]
        label = field_def.get("label", field_id)
        if role == "input":
            binding = file_bindings.get(field_id)
            if not binding:
                if field_def.get("required", True):
                    raise PublishedJobError(f"Field '{label}' requires a file or folder")
                continue
            resolved[field_id] = _resolve_input_binding(field_def, binding, workspaces, workspace_id, shared)
        else:  # output
            if workspaces is None or workspace_id is None:
                raise PublishedJobError(f"Field '{label}' is an output and requires a run workspace")
            base = str(workspaces.output_dir(workspace_id, field_id))
            # If this output overrides a fanned-out stage's output_dir, preserve
            # the per-item structure so its Tasks don't all overwrite one folder.
            out_binding = next(
                (b for b in field_def.get("bindings", []) if _is_stage_output_dir_binding(b)),
                None,
            )
            if out_binding is not None:
                template, ftype = _stage_output_template_and_fanout(
                    record.definition_content, out_binding["path"][1]
                )
                if ftype != "none":
                    base = _reroot_output_under_workspace(template, base)
            resolved[field_id] = base
    return resolved


def _resolve_input_binding(
    field_def: dict[str, Any],
    binding: dict[str, Any],
    workspaces: RunWorkspaceStore | None,
    workspace_id: str | None,
    shared: SharedStorage | None,
) -> str:
    label = field_def.get("label", field_def.get("id"))
    kind = binding.get("kind", "upload")
    path = str(binding.get("path", ""))
    if kind == "upload":
        if workspaces is None or workspace_id is None:
            raise PublishedJobError(f"Field '{label}' uses an upload but no run workspace was provided")
        try:
            if field_def.get("accept") == "directory":
                return str(workspaces.input_dir(workspace_id, field_def["id"]))
            return str(workspaces.input_abspath(workspace_id, path))
        except RunWorkspaceError as exc:
            raise PublishedJobError(f"Field '{label}': {exc}") from exc
    if kind == "shared":
        if shared is None:
            raise PublishedJobError(f"Field '{label}': shared storage is not configured")
        root_id = str(binding.get("root") or "")
        allowed = field_def.get("shared_roots") or []
        if not allowed:
            raise PublishedJobError(f"Field '{label}': no shared roots are permitted for this field")
        if root_id not in allowed:
            raise PublishedJobError(f"Field '{label}': shared root '{root_id}' is not allowed for this field")
        try:
            return str(shared.resolve(root_id, path))
        except SharedStorageError as exc:
            raise PublishedJobError(f"Field '{label}': {exc}") from exc
    raise PublishedJobError(f"Field '{label}': unknown input source '{kind}'")


def render_definition(record: PublishedJobRecord, values: dict[str, Any]) -> str:
    data = yaml.safe_load(record.definition_content)
    if not isinstance(data, dict):
        raise PublishedJobError("Published job definition must be a mapping")
    rendered = deepcopy(data)
    original_variables = data.get("variables") if isinstance(data.get("variables"), dict) else {}
    coerced_values = _coerce_values(record.fields, values)
    for field in record.fields:
        value = coerced_values[field["id"]]
        for binding in field.get("bindings", []):
            _apply_binding(rendered, binding, _reconcile_variable_value(original_variables, binding, value))
    # A $WILL_PROVIDE$ placeholder left in the rendered definition means a value
    # was never exposed as an input field — so the researcher had no way to supply
    # it. Fail here with an actionable message instead of letting the generic
    # "cannot be submitted directly" queue guard fire on the published-job path.
    leftover = _provided_later_locations(rendered)
    if leftover:
        raise PublishedJobError(
            f"This published job still has {PROVIDED_LATER} placeholder value(s) that were not "
            f"provided: {', '.join(leftover)}. Each must be exposed as a researcher input field."
        )
    content = yaml.safe_dump(rendered, sort_keys=False)
    parse_job_definition(content)
    return content


def _reconcile_variable_value(original_variables: dict[str, Any], binding: dict[str, Any], value: Any) -> Any:
    """Fill a researcher's matrix-variable selection out to the definition's full entry.

    A variable is exposed as an enum whose option values are the matrix entries
    captured when the field was inspected. If the definition later gains a field on
    those entries (e.g. a new ``{variant.group_cols}`` reference), an older stored
    option can be missing it — replacing ``variables.variant`` with that partial
    value leaves the new token unresolved at run time. So when a binding targets a
    whole ``variables.<name>`` and the chosen value is a dict, re-match it to the
    *current* definition entry by ``name`` and use that complete entry instead.
    """
    if binding.get("target") != "definition_path":
        return value
    path = binding.get("path")
    if not (isinstance(path, list) and len(path) == 2 and path[0] == "variables"):
        return value
    entries = original_variables.get(path[1])
    if not isinstance(entries, list) or not isinstance(value, dict):
        return value
    key = value.get("name")
    if key is None:
        return value
    for entry in entries:
        if isinstance(entry, dict) and entry.get("name") == key:
            return entry
    return value


def _provided_later_locations(data: Any, prefix: str = "") -> list[str]:
    """Dotted paths of every string in ``data`` still holding a PROVIDED_LATER placeholder."""
    found: list[str] = []
    if isinstance(data, str):
        if PROVIDED_LATER in data:
            found.append(prefix or "(value)")
    elif isinstance(data, dict):
        for key, value in data.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            found.extend(_provided_later_locations(value, child))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            found.extend(_provided_later_locations(value, f"{prefix}[{index}]"))
    return found


def public_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for field in fields:
        visible = {k: v for k, v in field.items() if k != "bindings"}
        cleaned.append(visible)
    return cleaned


def _stage_candidates(stage_name: str, stage: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        _candidate(
            f"stage_{stage_name}_output_dir",
            f"{stage_name}: output directory",
            "directory",
            f"Controls where the {stage_name} stage writes its outputs.",
            stage.get("output_dir", ""),
            [{"target": "definition_path", "path": ["stages", stage_name, "output_dir"]}],
            example=str(stage.get("output_dir", "")),
        )
    ]
    fanout = stage.get("fanout") or {}
    for key in ("type", "mapping", "data_dir", "raw_pattern", "meta_pattern"):
        if key in fanout:
            candidates.append(
                _candidate(
                    f"stage_{stage_name}_fanout_{key}",
                    f"{stage_name}: fan-out {key}",
                    "enum" if key == "type" else ("directory" if key == "data_dir" else "glob" if "pattern" in key else "path"),
                    f"Controls the fan-out {key} setting for the {stage_name} stage.",
                    fanout[key],
                    [{"target": "definition_path", "path": ["stages", stage_name, "fanout", key]}],
                    options=[{"label": item, "value": item} for item in sorted(["none", "mapping_file", "patterns", "folders"])]
                    if key == "type"
                    else [],
                    example=str(fanout[key]),
                )
            )
    for input_name, value in (stage.get("input_sources") or {}).items():
        candidates.append(
            _candidate(
                f"stage_{stage_name}_input_{input_name}",
                f"{stage_name}: input {input_name}",
                "file",
                f"Sets the input source used for {input_name} in the {stage_name} stage.",
                value,
                [{"target": "stage_input_source", "stage": stage_name, "input": input_name}],
                example=str(value),
            )
        )
    for process_name, params in (stage.get("process_arg_mapping") or {}).items():
        for param, value in params.items():
            candidates.append(
                _candidate(
                    f"stage_{stage_name}_process_{process_name}_{param}",
                    f"{stage_name}: {process_name}.{param}",
                    _infer_field_type(value),
                    f"Overrides the {param} parameter for process {process_name} in the {stage_name} stage.",
                    value,
                    [
                        {
                            "target": "stage_process_arg",
                            "stage": stage_name,
                            "process": process_name,
                            "parameter": param,
                        }
                    ],
                    example=str(value),
                )
            )
    return candidates


def _pipeline_candidates(stage_name: str, stage: dict[str, Any], yaml_loader: Callable[[str], str]) -> list[dict[str, Any]]:
    try:
        content = yaml_loader(stage["pipeline_yaml"])
        config = yaml.safe_load(content) or {}
    except Exception:
        return []
    pipeline_config = None
    for item in config.get("pipelines") or []:
        if isinstance(item, dict) and stage["pipeline"] in item:
            pipeline_config = item[stage["pipeline"]]
            break
    if not isinstance(pipeline_config, dict):
        return []
    candidates: list[dict[str, Any]] = []
    for input_entry in pipeline_config.get("Inputs") or []:
        if not isinstance(input_entry, dict):
            continue
        for input_name, raw_spec in input_entry.items():
            spec = _coerce_yaml_list_mapping(raw_spec)
            if not isinstance(spec, dict):
                continue
            for key, value in spec.items():
                if key in {"package", "method", "is_cached"}:
                    continue
                candidates.append(
                    _candidate(
                        f"stage_{stage_name}_inputarg_{input_name}_{key}",
                        f"{stage_name}: input {input_name}.{key}",
                        "file" if key == "src" else _infer_field_type(value),
                        f"Overrides the {key} argument passed to input {input_name} in the {stage_name} stage.",
                        value,
                        [
                            {"target": "stage_input_source", "stage": stage_name, "input": input_name}
                            if key == "src"
                            else {
                                "target": "stage_input_arg",
                                "stage": stage_name,
                                "input": input_name,
                                "parameter": key,
                            }
                        ],
                        example=str(value),
                    )
                )
    for process_entry in pipeline_config.get("Processes") or []:
        if not isinstance(process_entry, dict):
            continue
        for process_name, process_spec in process_entry.items():
            for param, value in (process_spec.get("parameters") or {}).items():
                candidates.append(
                    _candidate(
                        f"stage_{stage_name}_processarg_{process_name}_{param}",
                        f"{stage_name}: {process_name}.{param}",
                        _infer_field_type(value),
                        f"Overrides the {param} parameter for process {process_name} in the {stage_name} stage.",
                        value,
                        [
                            {
                                "target": "stage_process_arg",
                                "stage": stage_name,
                                "process": process_name,
                                "parameter": param,
                            }
                        ],
                        example=str(value),
                    )
                )
    for output_entry in pipeline_config.get("Outputs") or []:
        if not isinstance(output_entry, dict):
            continue
        for output_name, value in output_entry.items():
            candidates.append(
                _candidate(
                    f"stage_{stage_name}_output_{output_name}",
                    f"{stage_name}: output {output_name}",
                    "path",
                    f"Overrides the output path for payload {output_name} in the {stage_name} stage.",
                    value,
                    [{"target": "stage_output_path", "stage": stage_name, "output": output_name}],
                    example=str(value),
                )
            )
    return candidates


def _validate_definition_and_fields(definition_content: str, fields: list[dict[str, Any]]) -> None:
    parse_job_definition(definition_content)
    ids: set[str] = set()
    for field in fields:
        field_id = field.get("id")
        if not isinstance(field_id, str) or not field_id:
            raise PublishedJobError("Each field needs a non-empty id")
        if field_id in ids:
            raise PublishedJobError(f"Duplicate field id: {field_id}")
        ids.add(field_id)
        if field.get("type") not in FIELD_TYPES:
            raise PublishedJobError(f"Field '{field_id}' has unsupported type '{field.get('type')}'")
        if field.get("type") == "typed":
            if field.get("container", "single") not in CONTAINERS:
                raise PublishedJobError(f"Field '{field_id}' has an invalid container '{field.get('container')}'")
            if not isinstance(field.get("type_schema"), dict):
                raise PublishedJobError(
                    f"Field '{field_id}' is typed but has no resolved schema — choose a type from the library."
                )
        if not isinstance(field.get("bindings"), list) or not field["bindings"]:
            raise PublishedJobError(f"Field '{field_id}' needs at least one binding")


def resolve_typed_fields(fields: list[dict[str, Any]], library: dict[str, Any]) -> list[dict[str, Any]]:
    """Denormalize the resolved ``type_schema`` onto each typed field.

    Two sources of typed fields are supported:

    - **Library reference** (``schema_ref`` set): re-resolves ``type_schema`` from the
      project library on every save so the stored field tracks the current library.
    - **Inline definition** (``type == "typed"`` with no ``schema_ref``): ``type_schema``
      was resolved at inspect time from the job's own ``definitions:`` block and is
      already embedded — passed through unchanged.
    """
    resolved: list[dict[str, Any]] = []
    for field in fields:
        schema_ref = field.get("schema_ref")
        if schema_ref:
            # Library reference: re-resolve from the project type library.
            container = field.get("container", "single")
            if container not in CONTAINERS:
                raise PublishedJobError(f"Field '{field.get('id')}' has an invalid container '{container}'")
            try:
                type_schema = resolve_type(library, schema_ref)
            except TypeSchemaError as exc:
                raise PublishedJobError(str(exc)) from exc
            resolved.append({**field, "type": "typed", "container": container, "type_schema": type_schema})
        elif field.get("type") == "typed":
            # Inline typed field: type_schema was resolved from the job's definitions:
            # block at inspect time and is stored directly on the field.
            if not isinstance(field.get("type_schema"), dict):
                raise PublishedJobError(
                    f"Typed field '{field.get('id')}' has no type_schema; "
                    "add a schema_ref or re-inspect the job definition."
                )
            resolved.append(field)
        else:
            resolved.append(field)
    return resolved


def _coerce_values(fields: list[dict[str, Any]], values: dict[str, Any]) -> dict[str, Any]:
    coerced: dict[str, Any] = {}
    for field in fields:
        field_id = field["id"]
        raw = values[field_id] if field_id in values else field.get("default")
        # A value still holding the $WILL_PROVIDE$ placeholder means the researcher
        # never supplied it — always required, regardless of the field's own flag,
        # so the placeholder can never reach the queue.
        if contains_provided_later(raw):
            raise PublishedJobError(
                f"Field '{field.get('label', field_id)}' must be provided (it is marked {PROVIDED_LATER} in the job)."
            )
        if raw in (None, "") and field.get("required", True):
            raise PublishedJobError(f"Field '{field.get('label', field_id)}' is required")
        coerced[field_id] = _coerce_value(raw, field)
    return coerced


def _coerce_value(value: Any, field: dict[str, Any]) -> Any:
    field_type = field.get("type", "string")
    if value is None:
        return None
    if field_type == "integer":
        return int(value)
    if field_type == "float":
        return float(value)
    if field_type == "boolean":
        if isinstance(value, bool):
            return value
        if str(value).lower() in {"true", "1", "yes", "on"}:
            return True
        if str(value).lower() in {"false", "0", "no", "off"}:
            return False
        raise PublishedJobError(f"Field '{field.get('label', field.get('id'))}' must be boolean")
    if field_type in {"list", "multi_enum"}:
        return value if isinstance(value, list) else [value]
    if field_type in {"object", "json"}:
        if isinstance(value, str):
            return yaml.safe_load(value)
        return value
    if field_type == "typed":
        # A researcher may submit the structured value directly (dict/list) or, as a
        # fallback, as a JSON/YAML string from a plain textarea. Parse then validate
        # against the field's resolved schema, producing a native structure.
        if isinstance(value, str):
            value = yaml.safe_load(value)
        try:
            return coerce_typed_value(field, value)
        except TypeSchemaError as exc:
            raise PublishedJobError(str(exc)) from exc
    return value


def _apply_binding(data: dict[str, Any], binding: dict[str, Any], value: Any) -> None:
    target = binding.get("target")
    if target == "definition_path":
        path = binding.get("path")
        if not isinstance(path, list) or not path:
            raise PublishedJobError("definition_path binding needs a path")
        if path[0] == "stages":
            _set_stage_path(data, path[1:], value)
        else:
            if path[0] == "variables" and len(path) == 2 and not isinstance(value, list):
                value = [value]
            _set_path(data, path, value)
        return
    stage = _stage_by_name(data, str(binding.get("stage", "")))
    if target == "stage_input_source":
        # input_sources values are string `src` overrides. Coerce so a field of
        # the wrong type (e.g. an integer bound here by mistake) degrades to a
        # controlled pipeline error instead of crashing job serialization.
        stage.setdefault("input_sources", {})[binding["input"]] = (
            value if isinstance(value, str) else str(value)
        )
    elif target == "stage_input_arg":
        stage.setdefault("input_arg_mapping", {}).setdefault(binding["input"], {})[binding["parameter"]] = value
    elif target == "stage_process_arg":
        stage.setdefault("process_arg_mapping", {}).setdefault(binding["process"], {})[binding["parameter"]] = value
    elif target == "stage_output_path":
        stage.setdefault("output_path_mapping", {})[binding["output"]] = value
    else:
        raise PublishedJobError(f"Unknown field binding target: {target}")


def _set_stage_path(data: dict[str, Any], path: list[Any], value: Any) -> None:
    if not path:
        raise PublishedJobError("Stage path is empty")
    stage = _stage_by_name(data, str(path[0]))
    _set_path(stage, path[1:], value)


def _stage_by_name(data: dict[str, Any], stage_name: str) -> dict[str, Any]:
    for stage in data.get("stages", []):
        if isinstance(stage, dict) and stage.get("name") == stage_name:
            return stage
    raise PublishedJobError(f"Unknown stage in binding: {stage_name}")


def _set_path(data: dict[str, Any], path: list[Any], value: Any) -> None:
    cursor = data
    for key in path[:-1]:
        if key not in cursor or not isinstance(cursor[key], dict):
            cursor[key] = {}
        cursor = cursor[key]
    cursor[path[-1]] = value


def _candidate(
    field_id: str,
    label: str,
    field_type: str,
    help_text: str,
    default: Any,
    bindings: list[dict[str, Any]],
    *,
    options: list[dict[str, Any]] | None = None,
    example: str = "",
) -> dict[str, Any]:
    return {
        "id": field_id,
        "label": label,
        "type": field_type,
        "required": True,
        "default": default,
        "help": help_text,
        "example": example,
        "options": options or [],
        "bindings": bindings,
    }


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for candidate in candidates:
        key = json.dumps(candidate.get("bindings", []), sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _io_defaults(field_type: str, bindings: list[dict[str, Any]]) -> tuple[str, str]:
    """Propose a default I/O role + picker kind for a candidate field.

    Direction is inferred only where the binding target makes it unambiguous —
    an output payload/dir, or an input ``src`` — and from the obvious ``file`` /
    ``directory`` types. A genuinely ambiguous ``path`` (e.g. a "merges-later"
    root fragment) stays ``none`` so the admin classifies it at publish time.
    Returns ``(io_role, accept)``.
    """
    binding = bindings[0] if bindings else {}
    target = binding.get("target")
    path = binding.get("path")
    is_output_dir = (
        target == "definition_path"
        and isinstance(path, list)
        and bool(path)
        and path[-1] == "output_dir"
    )
    if target == "stage_output_path" or is_output_dir:
        return "output", "directory" if (is_output_dir or field_type == "directory") else "file"
    if target == "stage_input_source":
        return "input", "directory" if field_type == "directory" else "file"
    if field_type == "file":
        return "input", "file"
    if field_type == "directory":
        return "input", "directory"
    return "none", "file"


def _option_for_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        label = str(value.get("label") or value.get("name") or json.dumps(value, sort_keys=True))
        return {"label": label, "value": value}
    return {"label": str(value), "value": value}


def _infer_field_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    text = str(value)
    if any(token in text.lower() for token in ("*", "?")):
        return "glob"
    if any(token in text.lower() for token in ("/", "\\", ".csv", ".yaml", ".yml")):
        return "path"
    return "string"


def _coerce_yaml_list_mapping(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        result: dict[str, Any] = {}
        for item in raw:
            if isinstance(item, dict):
                result.update(item)
        return result
    return None


def _published_job_from_row(row: sqlite3.Row) -> PublishedJobRecord:
    return PublishedJobRecord(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        status=row["status"],
        version=int(row["version"]),
        definition_name=row["definition_name"],
        definition_content=row["definition_content"],
        fields=json.loads(row["fields"] or "[]"),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
        created_by=row["created_by"],
        updated_by=row["updated_by"],
    )


def _published_run_from_row(row: sqlite3.Row) -> PublishedRunRecord:
    return PublishedRunRecord(
        id=row["id"],
        published_job_id=row["published_job_id"],
        published_version=int(row["published_version"]),
        user_id=row["user_id"],
        values=json.loads(row["field_values"] or "{}"),
        rendered_definition=row["rendered_definition"],
        parent_job_id=row["parent_job_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        workspace_id=row["workspace_id"],
        file_bindings=json.loads(row["file_bindings"] or "{}"),
    )
