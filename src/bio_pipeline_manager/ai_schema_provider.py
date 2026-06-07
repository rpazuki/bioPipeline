from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import timezone
from pathlib import Path
from typing import Any

from bio_pipeline_manager.job_definition import FANOUT_TYPES
from bio_pipeline_manager.models import utc_now
from bio_pipeline_manager.published_jobs import FIELD_TYPES


@dataclass(frozen=True)
class AISchemaBundle:
    version: str
    generated_at: str
    digest: str
    pipeline_yaml: dict[str, Any]
    job_definition: dict[str, Any]
    published_job: dict[str, Any]
    api_tools: list[dict[str, Any]]
    examples: dict[str, str]
    notes: list[str]


class AISchemaProvider:
    def __init__(
        self,
        *,
        api_prefix: str = "/api/v1",
        tool_definitions: list[dict[str, Any]] | None = None,
        context_path: Path | None = None,
    ) -> None:
        self.api_prefix = api_prefix
        self.tool_definitions = tool_definitions or []
        repo_root = Path(__file__).resolve().parents[2]
        self.context_path = context_path or repo_root / "docs" / "AI_PIPELINE_DESIGNER_CONTEXT.md"

    def build_bundle(self) -> AISchemaBundle:
        content = {
            "version": "1",
            "pipeline_yaml": self._pipeline_yaml_schema(),
            "job_definition": self._job_definition_schema(),
            "published_job": self._published_job_schema(),
            "api_tools": self.tool_definitions,
            "examples": self._examples(),
            "notes": [
                (
                    "The dynamic schema bundle is authoritative when it "
                    "conflicts with older prose examples."
                ),
                "Tool arguments must match each tool's input_schema.",
                "Submitting a Job Definition to the queue requires confirmation.",
                (
                    "input_sources values are strings only (a file path, glob, or "
                    "directory). Never place numbers or booleans in input_sources."
                ),
                (
                    "Model scalar values (start, stop, step, counts, thresholds, "
                    "flags) as Process parameters, not as Inputs."
                ),
                (
                    "Publishing user-facing jobs is manual and out of scope; do "
                    "not design or create Published Jobs."
                ),
            ],
        }
        digest = self._digest(content)
        return AISchemaBundle(
            generated_at=utc_now().astimezone(timezone.utc).isoformat(),
            digest=digest,
            **content,
        )

    def build_prompt_context(self) -> str:
        """Compact schema context for the system prompt.

        The full bundle (with Pydantic JSON schemas, tool schemas, and example
        YAML) is large and would be re-sent on every tool-loop iteration. The
        verbose parts are dropped here because: tool schemas already travel via
        the provider ``tools`` parameter, example YAML already lives in the
        markdown context, and the Pydantic JSON schemas are available to the UI
        through ``GET /ai-chat/schema``. Only the compact structural rules and
        notes are kept so the model still has authoritative shape guidance.
        """
        bundle = self.build_bundle()
        # Published Jobs are out of the AI's scope (publishing is manual), so the
        # published_job schema is omitted from the model-facing prompt. It stays
        # in the full bundle for the /ai-chat/schema endpoint and UI.
        compact = {
            "version": bundle.version,
            "digest": bundle.digest,
            "pipeline_yaml": _drop(bundle.pipeline_yaml, "pydantic"),
            "job_definition": _drop(bundle.job_definition, "pydantic"),
            "notes": bundle.notes,
        }
        return json.dumps(compact, indent=2, sort_keys=True)

    def _pipeline_yaml_schema(self) -> dict[str, Any]:
        return {
            "summary": "Pipeline YAML is the lower-level executable pipeline format.",
            "required_top_level": ["pipelines"],
            "required_pipeline_sections": ["Inputs", "Processes", "Outputs"],
            "input_required_keys": ["src", "package", "method"],
            "process_required_keys": ["package", "method", "parameters"],
            "output_path_types": ["string", "list"],
            "pydantic": self._pydantic_schemas(
                [
                    "YamlSaveRequest",
                    "YamlDocument",
                    "ValidateYamlRequest",
                    "ValidationReportResponse",
                    "PipelineSummaryResponse",
                ]
            ),
        }

    def _job_definition_schema(self) -> dict[str, Any]:
        return {
            "summary": (
                "Job Definition YAML expands a declarative experiment into "
                "materialized tasks."
            ),
            "required_top_level": ["job", "stages"],
            "optional_top_level": ["description", "variables", "defaults"],
            "required_stage_keys": ["name", "pipeline_yaml", "pipeline", "output_dir"],
            "optional_stage_keys": [
                "needs",
                "fanout",
                "input_sources",
                "input_arg_mapping",
                "process_arg_mapping",
                "output_path_mapping",
            ],
            "fanout_types": sorted(FANOUT_TYPES),
            "template_tokens": [
                "matrix variables, e.g. {run_tag}",
                "mapping variable fields, e.g. {variant.name}",
                "defaults, e.g. {data_root}",
                "stage fanout data_dir as {data_dir}",
                "item.raw",
                "item.meta",
                "item.stem",
                "item.name",
                "item.path",
            ],
            "pydantic": self._pydantic_schemas(
                [
                    "DefinitionSaveRequest",
                    "DefinitionDocument",
                    "JobDefinitionRequest",
                    "JobDefinitionPreviewResponse",
                    "JobGroupDetail",
                ]
            ),
        }

    def _published_job_schema(self) -> dict[str, Any]:
        return {
            "summary": "Published Jobs expose a Job Definition as a user-facing form.",
            "statuses": ["draft", "published", "archived"],
            "field_types": sorted(FIELD_TYPES),
            "binding_targets": [
                "definition_path",
                "stage_input_source",
                "stage_input_arg",
                "stage_process_arg",
                "stage_output_path",
            ],
            "pydantic": self._pydantic_schemas(
                [
                    "PublishedField",
                    "PublishedJobInspectRequest",
                    "PublishedJobInspectResponse",
                    "PublishedJobSaveRequest",
                    "PublishedJobAdminResponse",
                ]
            ),
        }

    def _pydantic_schemas(self, names: list[str]) -> dict[str, Any]:
        try:
            from app.schemas import pipelines
        except Exception:
            return {}
        schemas: dict[str, Any] = {}
        for name in names:
            model = getattr(pipelines, name, None)
            if model is None or not hasattr(model, "model_json_schema"):
                continue
            schemas[name] = model.model_json_schema()
        return schemas

    def _examples(self) -> dict[str, str]:
        if not self.context_path.exists():
            return {}
        text = self.context_path.read_text(encoding="utf-8")
        examples: dict[str, str] = {}
        for heading in (
            "Minimal Pipeline YAML Example",
            "Minimal Job Definition Example",
            "Multi-Stage Job Definition Example",
        ):
            marker = f"## {heading}"
            start = text.find(marker)
            if start == -1:
                continue
            fence_start = text.find("```yaml", start)
            if fence_start == -1:
                continue
            content_start = text.find("\n", fence_start)
            fence_end = text.find("```", content_start + 1)
            if content_start == -1 or fence_end == -1:
                continue
            examples[heading] = text[content_start + 1 : fence_end].strip()
        return examples

    @staticmethod
    def _digest(content: dict[str, Any]) -> str:
        payload = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _drop(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in mapping.items() if name != key}
