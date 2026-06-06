"""Job Definition expansion.

A *Job Definition* is a declarative YAML that describes a whole experiment:

- ``variables``: a matrix of named values (scalars or dicts), expanded eagerly
  into one *cell* per cartesian combination.
- ``defaults``: shared values, templated against each cell.
- ``stages``: ordered pipeline steps. Each stage applies one pipeline (from its
  own ``pipeline_yaml``) over a *fan-out* of items, with templated
  ``output_dir`` / ``input_sources`` / ``process_arg_mapping``. ``needs``
  expresses ordering between stages of the same cell.

Expanding a definition yields a flat list of :class:`MaterializedTask` — each is
a single, fully-resolved pipeline invocation (the leaf the runner executes).

Templating uses ``{name}`` and ``{name.field}`` tokens resolved against the
cell bindings, the resolved defaults, the stage ``data_dir``, and the per-item
fields (``{item.raw}``, ``{item.meta}``, ``{item.stem}``, ``{item.path}``,
``{item.name}``).
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from pipeline.io import create_file_mapping_from_patterns, list_folders, load_file_mapping

_TOKEN_RE = re.compile(r"\{([a-zA-Z0-9_.]+)\}")

FANOUT_TYPES = {"none", "mapping_file", "patterns", "folders"}


class JobDefinitionError(ValueError):
    """Raised when a Job Definition is malformed or cannot be expanded."""


@dataclass(frozen=True)
class MaterializedTask:
    """One fully-resolved pipeline invocation produced by expansion."""

    job_name: str
    stage: str
    matrix_key: dict[str, str]
    needs: list[str]
    pipeline_yaml: str
    pipeline_name: str
    output_dir: str
    input_sources: dict[str, str] = field(default_factory=dict)
    process_arg_mapping: dict[str, dict[str, str]] = field(default_factory=dict)
    item_index: int = 0
    # True when a stage's fan-out source is not yet available (it will be
    # produced by an upstream stage at run time). Used only for preview display;
    # such stages are materialised lazily when they become eligible.
    deferred: bool = False


@dataclass(frozen=True)
class JobDefinition:
    name: str
    description: str
    variables: dict[str, list[Any]]
    defaults: dict[str, Any]
    stages: list[dict[str, Any]]


# --------------------------------------------------------------------------- #
# Parsing & validation
# --------------------------------------------------------------------------- #
def parse_job_definition(text: str) -> JobDefinition:
    """Parse and structurally validate a Job Definition YAML string."""
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise JobDefinitionError("Job Definition must be a mapping")
    if "job" not in data or not isinstance(data["job"], str):
        raise JobDefinitionError("Job Definition must have a string 'job' name")

    variables = data.get("variables", {}) or {}
    if not isinstance(variables, dict):
        raise JobDefinitionError("'variables' must be a mapping of name -> list")
    for var_name, values in variables.items():
        if not isinstance(values, list) or not values:
            raise JobDefinitionError(f"variable '{var_name}' must be a non-empty list")

    defaults = data.get("defaults", {}) or {}
    if not isinstance(defaults, dict):
        raise JobDefinitionError("'defaults' must be a mapping")

    stages = data.get("stages", []) or []
    if not isinstance(stages, list) or not stages:
        raise JobDefinitionError("Job Definition must have a non-empty 'stages' list")

    stage_names: set[str] = set()
    for stage in stages:
        if not isinstance(stage, dict):
            raise JobDefinitionError("each stage must be a mapping")
        name = stage.get("name")
        if not name or not isinstance(name, str):
            raise JobDefinitionError("each stage must have a string 'name'")
        if name in stage_names:
            raise JobDefinitionError(f"duplicate stage name '{name}'")
        stage_names.add(name)
        for required in ("pipeline", "pipeline_yaml", "output_dir"):
            if required not in stage:
                raise JobDefinitionError(f"stage '{name}' is missing required key '{required}'")
        fanout = stage.get("fanout", {"type": "none"}) or {"type": "none"}
        ftype = fanout.get("type", "none")
        if ftype not in FANOUT_TYPES:
            raise JobDefinitionError(f"stage '{name}' has unknown fanout type '{ftype}'")

    # Validate `needs` references and absence of cycles.
    for stage in stages:
        for dep in stage.get("needs", []) or []:
            if dep not in stage_names:
                raise JobDefinitionError(f"stage '{stage['name']}' needs unknown stage '{dep}'")
    _check_no_cycles(stages)

    return JobDefinition(
        name=data["job"],
        description=data.get("description", ""),
        variables=variables,
        defaults=defaults,
        stages=stages,
    )


def _check_no_cycles(stages: list[dict[str, Any]]) -> None:
    deps = {s["name"]: list(s.get("needs", []) or []) for s in stages}
    visited: dict[str, int] = {}  # 0 = visiting, 1 = done

    def visit(node: str, trail: list[str]) -> None:
        state = visited.get(node)
        if state == 1:
            return
        if state == 0:
            cycle = " -> ".join(trail + [node])
            raise JobDefinitionError(f"stage dependency cycle: {cycle}")
        visited[node] = 0
        for nxt in deps[node]:
            visit(nxt, trail + [node])
        visited[node] = 1

    for name in deps:
        visit(name, [])


# --------------------------------------------------------------------------- #
# Templating
# --------------------------------------------------------------------------- #
def _render(template: Any, context: dict[str, str], *, lenient: bool = False) -> Any:
    """Render ``{token}`` substitutions in strings / nested dicts / lists.

    With ``lenient=True`` an unknown token is left as-is instead of raising
    (used for preview of deferred stages, whose item fields are not yet known).
    """
    if isinstance(template, str):

        def replace(match: re.Match) -> str:
            key = match.group(1)
            if key not in context:
                if lenient:
                    return match.group(0)
                raise JobDefinitionError(f"unresolved template variable '{{{key}}}'")
            return str(context[key])

        return _TOKEN_RE.sub(replace, template)
    if isinstance(template, dict):
        return {k: _render(v, context, lenient=lenient) for k, v in template.items()}
    if isinstance(template, list):
        return [_render(v, context, lenient=lenient) for v in template]
    return template


def _flatten_binding(name: str, value: Any) -> dict[str, str]:
    """Expose a matrix binding as flat template keys.

    A scalar ``run_tag='a'`` -> ``{'run_tag': 'a'}``.
    A dict ``variant={'name':'x','pipeline':'p'}`` -> ``{'variant.name':'x', 'variant.pipeline':'p'}``.
    """
    if isinstance(value, dict):
        return {f"{name}.{k}": v for k, v in value.items()}
    return {name: value}


# --------------------------------------------------------------------------- #
# Expansion
# --------------------------------------------------------------------------- #
def iter_cells(job_def: JobDefinition) -> list[dict[str, Any]]:
    """Cartesian product of the variable matrix → one binding dict per cell."""
    if not job_def.variables:
        return [{}]
    names = list(job_def.variables)
    value_lists = [job_def.variables[n] for n in names]
    cells = []
    for combo in itertools.product(*value_lists):
        cells.append(dict(zip(names, combo)))  # noqa: B905
    return cells


def _cell_context(job_def: JobDefinition, cell: dict[str, Any]) -> dict[str, str]:
    """Flat template context for a cell: bindings + rendered defaults."""
    context: dict[str, str] = {}
    for name, value in cell.items():
        context.update(_flatten_binding(name, value))
    # Defaults are rendered in declaration order so later ones can use earlier.
    for key, value in job_def.defaults.items():
        context[key] = _render(value, context)
    return context


def cell_matrix_key(cell: dict[str, Any]) -> dict[str, str]:
    """The stable key identifying a matrix cell (dict variables use their name)."""
    return {k: (v if not isinstance(v, dict) else v.get("name", "")) for k, v in cell.items()}


def stage_names(job_def: JobDefinition) -> list[str]:
    return [stage["name"] for stage in job_def.stages]


def stage_by_name(job_def: JobDefinition, name: str) -> dict[str, Any]:
    for stage in job_def.stages:
        if stage["name"] == name:
            return stage
    raise JobDefinitionError(f"unknown stage '{name}'")


def _fanout_items(stage: dict[str, Any], context: dict[str, str]) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Resolve a stage's fan-out into per-item template fragments.

    Returns ``(items, extra_context)`` where ``extra_context`` includes the
    resolved ``data_dir`` (exposed to ``input_sources``/``output_dir`` templates).
    """
    fanout = stage.get("fanout", {"type": "none"}) or {"type": "none"}
    ftype = fanout.get("type", "none")
    extra: dict[str, str] = {}

    data_dir = fanout.get("data_dir")
    if data_dir is not None:
        extra["data_dir"] = _render(data_dir, context)

    if ftype == "none":
        return [{}], extra

    stage_name = stage.get("name", "?")
    item_context = {**context, **extra}

    if ftype == "mapping_file":
        if "mapping" not in fanout:
            raise JobDefinitionError(f"stage '{stage_name}' mapping_file fan-out requires a 'mapping' path")
        mapping_path = _render(fanout["mapping"], item_context)
        try:
            mapping = load_file_mapping(mapping_path)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise JobDefinitionError(
                f"stage '{stage_name}' could not read mapping file '{mapping_path}': {exc}"
            ) from exc
        items = [
            {"item.raw": raw, "item.meta": meta, "item.stem": Path(raw).stem, "item.name": Path(raw).name}
            for raw, meta in mapping.items()
        ]
        return items, extra

    if ftype == "patterns":
        for required in ("raw_pattern", "meta_pattern"):
            if required not in fanout:
                raise JobDefinitionError(f"stage '{stage_name}' patterns fan-out requires '{required}'")
        try:
            mapping = create_file_mapping_from_patterns(
                extra.get("data_dir", ""),
                _render(fanout["raw_pattern"], item_context),
                _render(fanout["meta_pattern"], item_context),
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise JobDefinitionError(f"stage '{stage_name}' patterns fan-out failed: {exc}") from exc
        items = [
            {"item.raw": raw, "item.meta": meta, "item.stem": Path(raw).stem, "item.name": Path(raw).name}
            for raw, meta in mapping.items()
        ]
        return items, extra

    if ftype == "folders":
        try:
            folders = list_folders(extra.get("data_dir", ""))
        except (FileNotFoundError, OSError) as exc:
            raise JobDefinitionError(
                f"stage '{stage_name}' folders fan-out could not list '{extra.get('data_dir', '')}': {exc}"
            ) from exc
        items = [
            {"item.path": str(p), "item.name": p.name, "item.stem": p.stem}
            for p in sorted(folders)
        ]
        return items, extra

    raise JobDefinitionError(f"unknown fanout type '{ftype}'")  # pragma: no cover - guarded in parse


def materialize_stage(
    job_def: JobDefinition,
    cell: dict[str, Any],
    stage: dict[str, Any],
    *,
    lenient: bool = False,
) -> list[MaterializedTask]:
    """Resolve one stage for one matrix cell into concrete Tasks.

    When ``lenient`` is set and the fan-out source cannot be read yet (it will be
    produced by an upstream stage at run time), a single ``deferred`` placeholder
    Task is returned instead of raising — so a preview can still show the plan.
    """
    context = _cell_context(job_def, cell)
    matrix_key = cell_matrix_key(cell)
    needs = list(stage.get("needs", []) or [])

    try:
        items, extra = _fanout_items(stage, context)
    except JobDefinitionError:
        if not lenient:
            raise
        return [
            MaterializedTask(
                job_name=job_def.name,
                stage=stage["name"],
                matrix_key=matrix_key,
                needs=needs,
                pipeline_yaml=_render(stage["pipeline_yaml"], context, lenient=True),
                pipeline_name=_render(stage["pipeline"], context, lenient=True),
                output_dir=_render(stage["output_dir"], context, lenient=True),
                input_sources=_render(stage.get("input_sources", {}) or {}, context, lenient=True),
                process_arg_mapping=_render(stage.get("process_arg_mapping", {}) or {}, context, lenient=True),
                item_index=-1,
                deferred=True,
            )
        ]

    tasks: list[MaterializedTask] = []
    for index, item in enumerate(items):
        item_context = {**context, **extra, **item}
        tasks.append(
            MaterializedTask(
                job_name=job_def.name,
                stage=stage["name"],
                matrix_key=matrix_key,
                needs=needs,
                pipeline_yaml=_render(stage["pipeline_yaml"], item_context),
                pipeline_name=_render(stage["pipeline"], item_context),
                output_dir=_render(stage["output_dir"], item_context),
                input_sources=_render(stage.get("input_sources", {}) or {}, item_context),
                process_arg_mapping=_render(stage.get("process_arg_mapping", {}) or {}, item_context),
                item_index=index,
            )
        )
    return tasks


def expand(text_or_def: str | JobDefinition, *, lenient: bool = False) -> list[MaterializedTask]:
    """Expand a Job Definition into a flat list of materialized Tasks.

    The matrix is expanded eagerly. Each stage's fan-out is resolved from the
    filesystem. With ``lenient=True`` (used for preview), a stage whose fan-out
    source is not yet available is shown as one ``deferred`` placeholder instead
    of raising; otherwise any problem raises :class:`JobDefinitionError`.
    """
    job_def = text_or_def if isinstance(text_or_def, JobDefinition) else parse_job_definition(text_or_def)

    tasks: list[MaterializedTask] = []
    for cell in iter_cells(job_def):
        for stage in job_def.stages:
            # Only a stage with unmet `needs` may legitimately defer (its source is
            # produced upstream). A first stage with a missing source is a real error.
            stage_lenient = lenient and bool(stage.get("needs"))
            tasks.extend(materialize_stage(job_def, cell, stage, lenient=stage_lenient))
    return tasks
