from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from bio_pipeline_manager.ai_providers import (
    AIProviderResult,
    ConversationMessage,
    ProviderToolCall,
    ResolvedAIProviderConfig,
    build_provider,
    resolve_provider_config,
)
from bio_pipeline_manager.ai_tools import AIToolExecution, AIToolRegistry

BASE_SYSTEM_PROMPT = (
    "You are the Bio Pipeline Manager AI Designer.\n"
    "You help admins design and save pipeline YAML and Job Definition YAML.\n"
    "Use tools to inspect existing YAML, validate pipeline YAML, and preview Job "
    "Definitions before claiming success.\n"
    "Never submit a Job Definition to the queue without explicit admin "
    "confirmation.\n"
    "Publishing user-facing jobs is handled manually outside this chat; do not "
    "design, create, or publish Published Jobs.\n"
    "Treat the schema bundle as authoritative when it conflicts with older "
    "prose examples.\n"
    "Keep responses short and operational. Format replies in concise Markdown; "
    "use tables when comparing options or listing fields/parameters."
)

# Draft kind for each tool whose result should surface a draft artifact in the UI.
_PIPELINE_DRAFT_TOOLS = {"save_pipeline_yaml", "get_pipeline_yaml", "validate_pipeline_yaml"}
_DEFINITION_DRAFT_TOOLS = {"save_job_definition", "get_job_definition", "preview_job_definition"}


class _MessageLike(Protocol):
    role: str
    content: str


class _SelectionLike(Protocol):
    provider: str | None
    model: str | None
    temperature: float | None
    max_tokens: int | None


class _SchemaProviderLike(Protocol):
    def build_prompt_context(self) -> str: ...


@dataclass
class AIChatOutcome:
    text: str
    tool_calls: list[AIToolExecution] = field(default_factory=list)
    drafts: list[dict[str, Any]] = field(default_factory=list)
    needs_confirmation: AIToolExecution | None = None
    usage: dict[str, int] = field(default_factory=dict)
    provider: str = ""
    model: str = ""


class AIChatAgent:
    """Run the provider tool loop on behalf of one admin request.

    The model may request tools, but only the backend executes them through the
    allowlisted :class:`AIToolRegistry`. Read-only and draft tools run
    automatically; high-impact tools halt the loop and ask the admin to confirm.
    """

    def __init__(
        self,
        *,
        registry: AIToolRegistry,
        schema_provider: _SchemaProviderLike,
        context_markdown: str,
        ai_config: dict[str, Any],
        api_prefix: str = "/api/v1",
        client_factory: Callable[[str], Any] = build_provider,
    ) -> None:
        self.registry = registry
        self.schema_provider = schema_provider
        self.context_markdown = context_markdown
        self.ai_config = ai_config
        self.api_prefix = api_prefix
        self.client_factory = client_factory

    def run(
        self,
        *,
        messages: list[_MessageLike],
        selection: _SelectionLike | None = None,
        confirmations: dict[str, bool] | None = None,
        active_pipeline_yaml: str = "",
        active_job_definition: str = "",
    ) -> AIChatOutcome:
        confirmations = confirmations or {}
        config = self._resolve_config(selection)
        client = self.client_factory(config.provider)
        # The system prompt is kept byte-identical across requests (no volatile
        # workspace, no timestamps) so providers can cache it once for the whole
        # session. Cache reads do not count toward the input-token-per-minute
        # rate limit, so only the first call pays for the large prefix.
        system_prompt = self._system_prompt()
        tools = self.registry.definitions()

        workspace = self._workspace_block(active_pipeline_yaml, active_job_definition)
        conversation = self._build_conversation(messages, workspace)

        max_iterations = int(self.ai_config.get("max_tool_iterations", 8))
        outcome = AIChatOutcome(text="", provider=config.provider, model=config.model)

        for _ in range(max(1, max_iterations)):
            result: AIProviderResult = client.complete(
                config=config,
                system_prompt=system_prompt,
                messages=conversation,
                tools=tools,
            )
            _accumulate_usage(outcome.usage, result.usage)
            if result.text:
                outcome.text = result.text
            if not result.tool_calls:
                break

            conversation.append(
                ConversationMessage(
                    role="assistant",
                    content=result.text,
                    tool_calls=tuple(result.tool_calls),
                )
            )
            if self._run_tool_calls(result.tool_calls, conversation, confirmations, outcome):
                break
        return outcome

    def _run_tool_calls(
        self,
        tool_calls: list[ProviderToolCall],
        conversation: list[ConversationMessage],
        confirmations: dict[str, bool],
        outcome: AIChatOutcome,
    ) -> bool:
        """Execute one round of tool calls. Return True if the loop must halt."""
        for call in tool_calls:
            confirmed = bool(confirmations.get(call.name)) or bool(confirmations.get(call.id))
            execution = self.registry.execute(call.name, call.arguments, confirmed=confirmed)
            outcome.tool_calls.append(execution)
            if execution.status == "pending_confirmation":
                outcome.needs_confirmation = execution
                return True
            outcome.drafts.extend(_drafts_from(call.name, call.arguments, execution))
            conversation.append(
                ConversationMessage(
                    role="tool",
                    tool_call_id=call.id,
                    tool_name=call.name,
                    # Feed the model a trimmed result. The full result still goes
                    # to the UI/drafts; the conversation only carries what the
                    # model needs to decide the next step, so large dumps (e.g.
                    # preview task lists) are not re-sent on every round.
                    tool_result=(
                        _model_tool_result(call.name, execution.result)
                        if execution.status == "succeeded"
                        else {"error": _cap_str(execution.error or "")}
                    ),
                )
            )
        return False

    def _resolve_config(self, selection: _SelectionLike | None) -> ResolvedAIProviderConfig:
        return resolve_provider_config(
            self.ai_config,
            provider=getattr(selection, "provider", None),
            model=getattr(selection, "model", None),
            temperature=getattr(selection, "temperature", None),
            max_tokens=getattr(selection, "max_tokens", None),
        )

    def _system_prompt(self) -> str:
        tool_names = ", ".join(tool["name"] for tool in self.registry.definitions())
        parts = [BASE_SYSTEM_PROMPT]
        if self.context_markdown:
            parts.append(f"<project_context>\n{self.context_markdown}\n</project_context>")
        parts.append(
            "<current_runtime>\n"
            f"api_prefix: {self.api_prefix}\n"
            f"available_tools: {tool_names}\n"
            "</current_runtime>"
        )
        parts.append(
            f"<schema_bundle>\n{self.schema_provider.build_prompt_context()}\n</schema_bundle>"
        )
        return "\n\n".join(parts)

    @staticmethod
    def _build_conversation(
        messages: list[_MessageLike], workspace: str
    ) -> list[ConversationMessage]:
        conversation = [
            ConversationMessage(role=_normalize_role(m.role), content=m.content)
            for m in messages
        ]
        # Attach the volatile workspace to the latest user turn rather than the
        # cached system prompt, so the cached prefix stays stable per session.
        if workspace:
            for index in range(len(conversation) - 1, -1, -1):
                if conversation[index].role == "user":
                    conversation[index] = ConversationMessage(
                        role="user",
                        content=f"{workspace}\n\n{conversation[index].content}",
                    )
                    break
        return conversation

    @staticmethod
    def _workspace_block(pipeline_yaml: str, job_definition: str) -> str:
        sections: list[str] = []
        if pipeline_yaml.strip():
            sections.append(f"<pipeline_yaml>\n{pipeline_yaml}\n</pipeline_yaml>")
        if job_definition.strip():
            sections.append(f"<job_definition>\n{job_definition}\n</job_definition>")
        if not sections:
            return ""
        body = "\n".join(sections)
        return (
            "<workspace_state>\n"
            "The admin's current editor drafts. Build on these unless asked to "
            "start fresh.\n"
            f"{body}\n"
            "</workspace_state>"
        )


# Caps on what a tool result contributes to the model conversation. These bound
# token growth (results are re-sent every round) without starving the model of
# the fields it needs to act.
_MAX_TOOL_RESULT_CHARS = 4000
_MAX_CONTENT_CHARS = 6000
_MAX_LIST_ITEMS = 60


def _cap_str(value: str, limit: int = _MAX_CONTENT_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n…[truncated {len(value) - limit} chars]"


def _model_tool_result(name: str, result: Any) -> Any:
    """Compact a tool result for the model conversation.

    Keeps the fields the model needs to continue (content for `get_*`, validity
    and issues for validators, names for saves) and drops verbose payloads
    (preview task lists, saved-content echoes, pipeline summaries) that would
    otherwise be re-sent on every subsequent provider call.
    """
    if not isinstance(result, dict):
        return _enforce_cap(result)

    if name == "validate_pipeline_yaml":
        out: Any = {"is_valid": result.get("is_valid"), "issues": result.get("issues", [])}
    elif name == "preview_job_definition":
        tasks = result.get("tasks") or []
        out = {
            "job_name": result.get("job_name"),
            "task_count": result.get("task_count"),
            "first_task": tasks[0] if tasks else None,
        }
    elif name == "save_pipeline_yaml":
        out = {
            "name": result.get("name"),
            "pipelines": result.get("pipelines"),
            "is_valid": result.get("is_valid"),
            "error": result.get("error"),
        }
    elif name == "save_job_definition":
        out = {
            "name": result.get("name"),
            "job": result.get("job"),
            "is_valid": result.get("is_valid"),
            "error": result.get("error"),
        }
    elif name == "get_pipeline_yaml":
        out = {
            "name": result.get("name"),
            "content": _cap_str(str(result.get("content", ""))),
            "pipelines": result.get("pipelines"),
            "is_valid": result.get("is_valid"),
            "error": result.get("error"),
        }
    elif name == "get_job_definition":
        out = {
            "name": result.get("name"),
            "content": _cap_str(str(result.get("content", ""))),
            "job": result.get("job"),
            "is_valid": result.get("is_valid"),
            "error": result.get("error"),
        }
    elif name == "get_runtime_info":
        out = {
            "yaml_count": result.get("yaml_count"),
            "definition_count": result.get("definition_count"),
            "yaml_files": (result.get("yaml_files") or [])[:_MAX_LIST_ITEMS],
        }
    elif name in ("list_pipeline_yamls", "list_job_definitions"):
        items = result.get("items") or []
        out = {"count": len(items), "items": items[:_MAX_LIST_ITEMS]}
    else:
        out = result
    return _enforce_cap(out)


def _enforce_cap(out: Any) -> Any:
    payload = json.dumps(out, default=str)
    if len(payload) <= _MAX_TOOL_RESULT_CHARS:
        return out
    return {"truncated": True, "preview": payload[:_MAX_TOOL_RESULT_CHARS]}


def _normalize_role(role: str) -> str:
    return "assistant" if role == "assistant" else "user"


def _accumulate_usage(total: dict[str, int], delta: dict[str, int]) -> None:
    for key, value in (delta or {}).items():
        total[key] = int(total.get(key, 0)) + int(value or 0)


def _drafts_from(
    name: str, arguments: dict[str, Any], execution: AIToolExecution
) -> list[dict[str, Any]]:
    if execution.status != "succeeded":
        return []
    result = execution.result or {}
    if name in _PIPELINE_DRAFT_TOOLS:
        return [
            {
                "kind": "pipeline_yaml",
                "name": str(result.get("name", arguments.get("name", ""))),
                "content": result.get("content", arguments.get("content", "")),
                "source": "tool",
            }
        ]
    if name in _DEFINITION_DRAFT_TOOLS:
        return [
            {
                "kind": "job_definition",
                "name": str(result.get("name", arguments.get("name", ""))),
                "content": result.get("content", arguments.get("content", "")),
                "source": "tool",
            }
        ]
    return []
