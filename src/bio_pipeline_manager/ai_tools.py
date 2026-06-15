from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from bio_pipeline_manager.job_definition import expand, fanout_warnings, parse_job_definition
from bio_pipeline_manager.published_jobs import inspect_definition
from bio_pipeline_manager.yaml_validation import validate_labutils_yaml


@dataclass(frozen=True)
class AIToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool = True
    requires_confirmation: bool = False
    # When False, the tool is hidden from the model's advertised tool list (so the
    # agent can never call it) but is still reachable through the registry's
    # ``execute`` path — i.e. only an explicit admin UI action can run it. The save
    # tools use this so the AI drafts artifacts but never persists them; the admin
    # saves via the Save button in each draft box.
    model_callable: bool = True


@dataclass(frozen=True)
class AIToolExecution:
    id: str
    name: str
    arguments: dict[str, Any]
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    requires_confirmation: bool = False


@dataclass(frozen=True)
class _Tool:
    definition: AIToolDefinition
    handler: Callable[[dict[str, Any]], dict[str, Any]]


class AIToolRegistry:
    def __init__(self, runtime, *, actor: str = "ai-agent") -> None:
        self.runtime = runtime
        self.actor = actor
        self._tools = self._build_tools()

    def definitions(self) -> list[dict[str, Any]]:
        """Tool definitions advertised to the model.

        Only model-callable tools are exposed, so the agent's tool loop can never
        request a non-model-callable tool (e.g. the save tools). The full set,
        including admin-UI-only tools, is still reachable through :meth:`execute`.
        """
        return [
            asdict(tool.definition)
            for tool in self._tools.values()
            if tool.definition.model_callable
        ]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        confirmed: bool = False,
    ) -> AIToolExecution:
        args = arguments or {}
        tool = self._tools.get(name)
        if tool is None:
            return AIToolExecution(
                id=uuid4().hex,
                name=name,
                arguments=args,
                status="failed",
                error=f"Unknown AI tool: {name}",
            )
        if tool.definition.requires_confirmation and not confirmed:
            return AIToolExecution(
                id=uuid4().hex,
                name=name,
                arguments=args,
                status="pending_confirmation",
                requires_confirmation=True,
            )
        try:
            return AIToolExecution(
                id=uuid4().hex,
                name=name,
                arguments=args,
                status="succeeded",
                result=tool.handler(args),
                requires_confirmation=tool.definition.requires_confirmation,
            )
        except Exception as exc:  # noqa: BLE001 - tool errors must reach the model, not 500
            # Any tool failure is reported back as a failed tool result so the
            # model can react. It must never propagate and crash the request.
            return AIToolExecution(
                id=uuid4().hex,
                name=name,
                arguments=args,
                status="failed",
                error=str(exc),
                requires_confirmation=tool.definition.requires_confirmation,
            )

    def _build_tools(self) -> dict[str, _Tool]:
        tools = [
            _Tool(
                AIToolDefinition(
                    name="get_runtime_info",
                    description="Return runtime paths and storage counts.",
                    input_schema=_object_schema({}),
                ),
                self._get_runtime_info,
            ),
            _Tool(
                AIToolDefinition(
                    name="list_pipeline_yamls",
                    description="List stored Pipeline YAML files and known pipeline names.",
                    input_schema=_object_schema({}),
                ),
                self._list_pipeline_yamls,
            ),
            _Tool(
                AIToolDefinition(
                    name="get_pipeline_yaml",
                    description="Load one stored Pipeline YAML file.",
                    input_schema=_object_schema({"name": {"type": "string"}}, required=["name"]),
                ),
                self._get_pipeline_yaml,
            ),
            _Tool(
                AIToolDefinition(
                    name="validate_pipeline_yaml",
                    description="Validate raw Pipeline YAML content.",
                    input_schema=_object_schema(
                        {"content": {"type": "string"}, "imports": {"type": "boolean"}},
                        required=["content"],
                    ),
                ),
                self._validate_pipeline_yaml,
            ),
            _Tool(
                AIToolDefinition(
                    name="list_job_definitions",
                    description="List saved Job Definition YAML files.",
                    input_schema=_object_schema({}),
                ),
                self._list_job_definitions,
            ),
            _Tool(
                AIToolDefinition(
                    name="get_job_definition",
                    description="Load one saved Job Definition YAML file.",
                    input_schema=_object_schema({"name": {"type": "string"}}, required=["name"]),
                ),
                self._get_job_definition,
            ),
            _Tool(
                AIToolDefinition(
                    name="preview_job_definition",
                    description="Expand a Job Definition without queueing tasks.",
                    input_schema=_object_schema(
                        {"content": {"type": "string"}},
                        required=["content"],
                    ),
                ),
                self._preview_job_definition,
            ),
            _Tool(
                AIToolDefinition(
                    name="inspect_published_job_fields",
                    description=(
                        "Derive the definable input/output fields of a Published Job from a "
                        "Job Definition. Use this to design a user-facing Published Job draft; "
                        "the admin saves it from the Published Job box (you never save it)."
                    ),
                    input_schema=_object_schema(
                        {
                            "content": {"type": "string"},
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "definition_name": {"type": "string"},
                        },
                        required=["content"],
                    ),
                ),
                self._inspect_published_job_fields,
            ),
            _Tool(
                AIToolDefinition(
                    name="save_pipeline_yaml",
                    description="Save Pipeline YAML into the YAML store.",
                    input_schema=_object_schema(
                        {
                            "name": {"type": "string"},
                            "content": {"type": "string"},
                            "overwrite": {"type": "boolean"},
                        },
                        required=["name", "content"],
                    ),
                    read_only=False,
                    model_callable=False,
                ),
                self._save_pipeline_yaml,
            ),
            _Tool(
                AIToolDefinition(
                    name="save_job_definition",
                    description="Save Job Definition YAML into the Job Definition store.",
                    input_schema=_object_schema(
                        {
                            "name": {"type": "string"},
                            "content": {"type": "string"},
                            "overwrite": {"type": "boolean"},
                        },
                        required=["name", "content"],
                    ),
                    read_only=False,
                    model_callable=False,
                ),
                self._save_job_definition,
            ),
            _Tool(
                AIToolDefinition(
                    name="submit_job_definition",
                    description="Submit a Job Definition to the queue.",
                    input_schema=_object_schema(
                        {
                            "content": {"type": "string"},
                            "scheduled_at": {"type": ["string", "null"]},
                        },
                        required=["content"],
                    ),
                    read_only=False,
                    requires_confirmation=True,
                ),
                self._submit_job_definition,
            ),
            _Tool(
                AIToolDefinition(
                    name="run_due_jobs",
                    description="Run due queued jobs.",
                    input_schema=_object_schema({"parallel": {"type": "integer"}}, required=[]),
                    read_only=False,
                    requires_confirmation=True,
                ),
                self._run_due_jobs,
            ),
        ]
        return {tool.definition.name: tool for tool in tools}

    def _get_runtime_info(self, _args: dict[str, Any]) -> dict[str, Any]:
        return {
            "pipeline_home": str(self.runtime.home),
            "yaml_root": str(self.runtime.yaml_store.root),
            "yaml_count": len(self.runtime.yaml_store.list()),
            "yaml_files": [
                self.runtime.yaml_store.relative_name(path)
                for path in self.runtime.yaml_store.list()
            ],
            "definition_count": len(self.runtime.definition_store.list()),
        }

    def _list_pipeline_yamls(self, _args: dict[str, Any]) -> dict[str, Any]:
        items = []
        for path in self.runtime.yaml_store.list():
            name = self.runtime.yaml_store.relative_name(path)
            try:
                items.append(
                    {
                        "name": name,
                        "pipelines": self.runtime.yaml_store.pipeline_names(name),
                        "is_valid": True,
                    }
                )
            except ValueError as exc:
                items.append({"name": name, "pipelines": [], "is_valid": False, "error": str(exc)})
        return {"items": items}

    def _get_pipeline_yaml(self, args: dict[str, Any]) -> dict[str, Any]:
        name = _required_str(args, "name")
        content = self.runtime.yaml_store.load(name)
        try:
            pipelines = self.runtime.yaml_store.pipeline_names(name)
            return {
                "name": name,
                "content": content,
                "pipelines": pipelines,
                "is_valid": True,
                "error": None,
            }
        except ValueError as exc:
            return {
                "name": name,
                "content": content,
                "pipelines": [],
                "is_valid": False,
                "error": str(exc),
            }

    def _validate_pipeline_yaml(self, args: dict[str, Any]) -> dict[str, Any]:
        content = _required_str(args, "content")
        report = validate_labutils_yaml(content, validate_imports=bool(args.get("imports", False)))
        return report.as_dict()

    def _list_job_definitions(self, _args: dict[str, Any]) -> dict[str, Any]:
        items = []
        store = self.runtime.definition_store
        for path in store.list():
            name = store.relative_name(path)
            job, description, is_valid, error = store.summary(name)
            items.append({"name": name, "job": job, "description": description, "is_valid": is_valid, "error": error})
        return {"items": items}

    def _get_job_definition(self, args: dict[str, Any]) -> dict[str, Any]:
        name = _required_str(args, "name")
        content = self.runtime.definition_store.load(name)
        job, description, is_valid, error = self.runtime.definition_store.summary(name)
        return {"name": name, "content": content, "job": job, "description": description, "is_valid": is_valid, "error": error}

    def _preview_job_definition(self, args: dict[str, Any]) -> dict[str, Any]:
        tasks = expand(_required_str(args, "content"), lenient=True)
        return {
            "job_name": tasks[0].job_name if tasks else "",
            "task_count": len(tasks),
            "tasks": [_serialize(task) for task in tasks],
        }

    def _inspect_published_job_fields(self, args: dict[str, Any]) -> dict[str, Any]:
        content = _required_str(args, "content")
        job_def = parse_job_definition(content)
        candidates = inspect_definition(
            content,
            yaml_loader=self.runtime.yaml_store.load,
            type_library=self.runtime.type_library.all(),
        )
        return {
            "job_name": job_def.name,
            "name": str(args.get("name") or job_def.name),
            "description": str(args.get("description") or ""),
            "definition_name": str(args.get("definition_name") or ""),
            "definition_content": content,
            "candidates": candidates,
            "warnings": fanout_warnings(job_def),
        }

    def _save_pipeline_yaml(self, args: dict[str, Any]) -> dict[str, Any]:
        name = _required_str(args, "name")
        content = _required_str(args, "content")
        path = self.runtime.yaml_store.save(
            name,
            content,
            overwrite=bool(args.get("overwrite", True)),
        )
        resolved_name = self.runtime.yaml_store.relative_name(path)
        return self._get_pipeline_yaml({"name": resolved_name})

    def _save_job_definition(self, args: dict[str, Any]) -> dict[str, Any]:
        name = _required_str(args, "name")
        content = _required_str(args, "content")
        path = self.runtime.definition_store.save(
            name,
            content,
            overwrite=bool(args.get("overwrite", True)),
        )
        resolved_name = self.runtime.definition_store.relative_name(path)
        return self._get_job_definition({"name": resolved_name})

    def _submit_job_definition(self, args: dict[str, Any]) -> dict[str, Any]:
        parent_id, _records = self.runtime.queue.submit_definition(
            _required_str(args, "content"),
            yaml_resolver=self.runtime.yaml_store.resolve_name,
            scheduled_at=args.get("scheduled_at"),
        )
        return {
            "parent_job_id": parent_id,
            "group": _serialize(self.runtime.queue.group_status(parent_id)),
        }

    def _run_due_jobs(self, args: dict[str, Any]) -> dict[str, Any]:
        parallel = int(args.get("parallel", 1))
        return {"jobs": [_serialize(job) for job in self.runtime.queue.run_due(parallel=parallel)]}


def _object_schema(
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _required_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Tool argument '{key}' must be a non-empty string")
    return value


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    return value
