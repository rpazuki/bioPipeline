from __future__ import annotations

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
    "You help admins design pipeline YAML, Job Definition YAML, and Published "
    "Jobs.\n"
    "Use tools to inspect existing YAML and validate drafts before finalizing.\n"
    "Validate pipeline YAML and preview Job Definitions before claiming success.\n"
    "Never submit or publish without explicit admin confirmation.\n"
    "Treat the schema bundle as authoritative when it conflicts with older "
    "prose examples.\n"
    "Keep responses short and operational."
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
    ) -> AIChatOutcome:
        confirmations = confirmations or {}
        config = self._resolve_config(selection)
        client = self.client_factory(config.provider)
        system_prompt = self._system_prompt()
        tools = self.registry.definitions()

        conversation: list[ConversationMessage] = [
            ConversationMessage(role=_normalize_role(m.role), content=m.content)
            for m in messages
        ]

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
                    tool_result=(
                        execution.result
                        if execution.status == "succeeded"
                        else {"error": execution.error}
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
    if name == "inspect_published_job_fields":
        return [
            {
                "kind": "published_fields",
                "name": "",
                "content": result.get("candidates", []),
                "source": "tool",
            }
        ]
    if name == "create_published_job_draft":
        return [
            {
                "kind": "published_fields",
                "name": str(result.get("name", arguments.get("name", ""))),
                "content": result.get("fields", []),
                "source": "tool",
            }
        ]
    return []
