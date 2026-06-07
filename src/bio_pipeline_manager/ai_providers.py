from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import uuid4


AIProviderName = Literal["claude", "openai", "gemini", "openai_compatible", "fake"]

# Conservative network guards for provider HTTP calls.
HTTP_TIMEOUT_SECONDS = 60.0
MAX_RESPONSE_BYTES = 8_000_000

KNOWN_PROVIDERS: tuple[str, ...] = ("claude", "openai", "gemini", "openai_compatible", "fake")


@dataclass(frozen=True)
class ProviderStatus:
    provider: str
    enabled: bool
    configured: bool
    model: str
    base_url: str
    is_default: bool = False


@dataclass(frozen=True)
class ResolvedAIProviderConfig:
    provider: str
    api_key: str
    model: str
    base_url: str
    temperature: float
    max_tokens: int


def provider_statuses(ai_config: dict[str, Any]) -> list[ProviderStatus]:
    providers = (
        ai_config.get("providers", {})
        if isinstance(ai_config.get("providers"), dict)
        else {}
    )
    default_provider = str(ai_config.get("default_provider", "claude"))
    statuses: list[ProviderStatus] = []
    for provider, raw in providers.items():
        if not isinstance(raw, dict):
            continue
        statuses.append(
            ProviderStatus(
                provider=provider,
                enabled=bool(raw.get("enabled", False)),
                configured=bool(str(raw.get("api_key", "")).strip()) or provider == "fake",
                model=str(raw.get("model", "")),
                base_url=str(raw.get("base_url", "")),
                is_default=provider == default_provider,
            )
        )
    return statuses


def resolve_provider_config(
    ai_config: dict[str, Any],
    *,
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> ResolvedAIProviderConfig:
    providers = (
        ai_config.get("providers", {})
        if isinstance(ai_config.get("providers"), dict)
        else {}
    )
    provider_name = provider or str(ai_config.get("default_provider", "claude"))
    if provider_name not in providers:
        raise ValueError(f"AI provider is not configured: {provider_name}")
    raw = providers[provider_name]
    if not isinstance(raw, dict):
        raise ValueError(f"AI provider config is invalid: {provider_name}")
    if not bool(raw.get("enabled", False)):
        raise ValueError(f"AI provider is disabled: {provider_name}")
    api_key = str(raw.get("api_key", ""))
    if provider_name != "fake" and not api_key.strip():
        raise ValueError(f"AI provider is missing an API key: {provider_name}")
    resolved_model = model if model is not None else str(raw.get("model", ""))
    if provider_name != "fake" and not resolved_model.strip():
        raise ValueError(f"AI provider is missing a model: {provider_name}")
    return ResolvedAIProviderConfig(
        provider=provider_name,
        api_key=api_key,
        model=resolved_model,
        base_url=str(raw.get("base_url", "")),
        temperature=(
            temperature
            if temperature is not None
            else float(ai_config.get("temperature", 0.2))
        ),
        max_tokens=max_tokens if max_tokens is not None else int(ai_config.get("max_tokens", 4096)),
    )


def provider_test_result(ai_config: dict[str, Any], **selection: Any) -> dict[str, Any]:
    resolved = resolve_provider_config(ai_config, **selection)
    return {
        "ok": True,
        "provider": resolved.provider,
        "model": resolved.model,
        "message": (
            "Provider configuration is present and a provider client is available."
        ),
    }


def redact_provider_error(message: str, ai_config: dict[str, Any]) -> str:
    redacted = message
    providers = (
        ai_config.get("providers", {})
        if isinstance(ai_config.get("providers"), dict)
        else {}
    )
    for raw in providers.values():
        if not isinstance(raw, dict):
            continue
        api_key = str(raw.get("api_key", ""))
        if api_key:
            redacted = redacted.replace(api_key, "[redacted]")
    return redacted


# ---------------------------------------------------------------------------
# Provider client layer
#
# The backend mediates every provider call. Adapters translate one
# provider-neutral conversation into each vendor's HTTP API and normalize the
# response back into AIProviderResult. The browser never calls a provider
# directly and never receives an API key.
# ---------------------------------------------------------------------------


class AIProviderError(RuntimeError):
    """Raised when a provider request fails or returns an unusable response."""


@dataclass(frozen=True)
class ProviderToolCall:
    """A tool the model asked the backend to run."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ConversationMessage:
    """Provider-neutral turn. Adapters translate this to a vendor payload.

    - ``user``/``assistant`` turns carry ``content`` (and assistant turns may
      carry ``tool_calls``).
    - ``tool`` turns carry the result of one executed tool call.
    """

    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ProviderToolCall, ...] = ()
    tool_call_id: str = ""
    tool_name: str = ""
    tool_result: Any = None


@dataclass(frozen=True)
class AIProviderResult:
    text: str
    tool_calls: list[ProviderToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    stop_reason: str = ""


class AIProviderClient(Protocol):
    name: str

    def complete(
        self,
        *,
        config: ResolvedAIProviderConfig,
        system_prompt: str,
        messages: list[ConversationMessage],
        tools: list[dict[str, Any]],
    ) -> AIProviderResult: ...


def build_provider(name: str) -> AIProviderClient:
    clients: dict[str, type[AIProviderClient]] = {
        "claude": ClaudeProviderClient,
        "openai": OpenAIProviderClient,
        "gemini": GeminiProviderClient,
        "openai_compatible": OpenAICompatibleProviderClient,
        "fake": FakeProviderClient,
    }
    client_cls = clients.get(name)
    if client_cls is None:
        raise AIProviderError(f"Unsupported AI provider: {name}")
    return client_cls()


def _post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    import httpx

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:  # network/timeout failures
        raise AIProviderError(f"Provider request failed: {exc}") from exc
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise AIProviderError("Provider response exceeded the size limit.")
    if response.status_code >= 400:
        raise AIProviderError(
            f"Provider returned HTTP {response.status_code}: {response.text[:500]}"
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise AIProviderError("Provider returned a non-JSON response.") from exc
    if not isinstance(data, dict):
        raise AIProviderError("Provider returned an unexpected response shape.")
    return data


def _tool_result_text(message: ConversationMessage) -> str:
    return json.dumps(message.tool_result, default=str)


class ClaudeProviderClient:
    """Anthropic Messages API adapter."""

    name = "claude"

    def complete(
        self,
        *,
        config: ResolvedAIProviderConfig,
        system_prompt: str,
        messages: list[ConversationMessage],
        tools: list[dict[str, Any]],
    ) -> AIProviderResult:
        base_url = (config.base_url or "https://api.anthropic.com").rstrip("/")
        payload: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "system": system_prompt,
            "messages": self._messages(messages),
        }
        if tools:
            payload["tools"] = [
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("input_schema", {"type": "object"}),
                }
                for tool in tools
            ]
        data = _post_json(
            f"{base_url}/v1/messages",
            headers={
                "x-api-key": config.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            payload=payload,
        )
        return self._parse(data, config)

    @staticmethod
    def _messages(messages: list[ConversationMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "tool":
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.tool_call_id,
                                "content": _tool_result_text(message),
                            }
                        ],
                    }
                )
                continue
            if message.role == "assistant" and message.tool_calls:
                blocks: list[dict[str, Any]] = []
                if message.content:
                    blocks.append({"type": "text", "text": message.content})
                for call in message.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.name,
                            "input": call.arguments,
                        }
                    )
                out.append({"role": "assistant", "content": blocks})
                continue
            out.append({"role": message.role, "content": message.content})
        return out

    @staticmethod
    def _parse(data: dict[str, Any], config: ResolvedAIProviderConfig) -> AIProviderResult:
        text_parts: list[str] = []
        tool_calls: list[ProviderToolCall] = []
        for block in data.get("content", []) or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ProviderToolCall(
                        id=str(block.get("id") or uuid4().hex),
                        name=str(block.get("name", "")),
                        arguments=dict(block.get("input", {}) or {}),
                    )
                )
        usage_raw = data.get("usage", {}) or {}
        usage = {
            "input_tokens": int(usage_raw.get("input_tokens", 0) or 0),
            "output_tokens": int(usage_raw.get("output_tokens", 0) or 0),
        }
        return AIProviderResult(
            text="".join(text_parts).strip(),
            tool_calls=tool_calls,
            usage=usage,
            provider=config.provider,
            model=config.model,
            stop_reason=str(data.get("stop_reason", "")),
        )


class OpenAIProviderClient:
    """OpenAI Chat Completions API adapter."""

    name = "openai"
    _default_base_url = "https://api.openai.com/v1"

    def complete(
        self,
        *,
        config: ResolvedAIProviderConfig,
        system_prompt: str,
        messages: list[ConversationMessage],
        tools: list[dict[str, Any]],
    ) -> AIProviderResult:
        base_url = (config.base_url or self._default_base_url).rstrip("/")
        if not base_url:
            raise AIProviderError(f"Provider is missing a base_url: {config.provider}")
        payload: dict[str, Any] = {
            "model": config.model,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "messages": self._messages(system_prompt, messages),
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {"type": "object"}),
                    },
                }
                for tool in tools
            ]
        data = _post_json(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "content-type": "application/json",
            },
            payload=payload,
        )
        return self._parse(data, config)

    @staticmethod
    def _messages(
        system_prompt: str, messages: list[ConversationMessage]
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for message in messages:
            if message.role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": _tool_result_text(message),
                    }
                )
                continue
            if message.role == "assistant" and message.tool_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": message.content or None,
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": json.dumps(call.arguments),
                                },
                            }
                            for call in message.tool_calls
                        ],
                    }
                )
                continue
            out.append({"role": message.role, "content": message.content})
        return out

    @staticmethod
    def _parse(data: dict[str, Any], config: ResolvedAIProviderConfig) -> AIProviderResult:
        choices = data.get("choices", []) or []
        message = choices[0].get("message", {}) if choices else {}
        tool_calls: list[ProviderToolCall] = []
        for raw in message.get("tool_calls", []) or []:
            function = raw.get("function", {}) if isinstance(raw, dict) else {}
            arguments = function.get("arguments", "{}")
            try:
                parsed = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
            except (ValueError, TypeError):
                parsed = {}
            tool_calls.append(
                ProviderToolCall(
                    id=str(raw.get("id") or uuid4().hex),
                    name=str(function.get("name", "")),
                    arguments=parsed if isinstance(parsed, dict) else {},
                )
            )
        usage_raw = data.get("usage", {}) or {}
        usage = {
            "input_tokens": int(usage_raw.get("prompt_tokens", 0) or 0),
            "output_tokens": int(usage_raw.get("completion_tokens", 0) or 0),
        }
        return AIProviderResult(
            text=str(message.get("content") or "").strip(),
            tool_calls=tool_calls,
            usage=usage,
            provider=config.provider,
            model=config.model,
            stop_reason=str(choices[0].get("finish_reason", "")) if choices else "",
        )


class OpenAICompatibleProviderClient(OpenAIProviderClient):
    """OpenAI-compatible servers. Identical wire format, operator base_url."""

    name = "openai_compatible"
    _default_base_url = ""


class GeminiProviderClient:
    """Google Gemini generateContent API adapter."""

    name = "gemini"

    def complete(
        self,
        *,
        config: ResolvedAIProviderConfig,
        system_prompt: str,
        messages: list[ConversationMessage],
        tools: list[dict[str, Any]],
    ) -> AIProviderResult:
        base_url = (config.base_url or "https://generativelanguage.googleapis.com").rstrip("/")
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": self._contents(messages),
            "generationConfig": {
                "temperature": config.temperature,
                "maxOutputTokens": config.max_tokens,
            },
        }
        if tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "parameters": tool.get("input_schema", {"type": "object"}),
                        }
                        for tool in tools
                    ]
                }
            ]
        url = f"{base_url}/v1beta/models/{config.model}:generateContent?key={config.api_key}"
        data = _post_json(
            url,
            headers={"content-type": "application/json"},
            payload=payload,
        )
        return self._parse(data, config)

    @staticmethod
    def _contents(messages: list[ConversationMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "tool":
                out.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": message.tool_name,
                                    "response": {"result": message.tool_result},
                                }
                            }
                        ],
                    }
                )
                continue
            if message.role == "assistant" and message.tool_calls:
                parts: list[dict[str, Any]] = []
                if message.content:
                    parts.append({"text": message.content})
                for call in message.tool_calls:
                    parts.append({"functionCall": {"name": call.name, "args": call.arguments}})
                out.append({"role": "model", "parts": parts})
                continue
            role = "model" if message.role == "assistant" else "user"
            out.append({"role": role, "parts": [{"text": message.content}]})
        return out

    @staticmethod
    def _parse(data: dict[str, Any], config: ResolvedAIProviderConfig) -> AIProviderResult:
        candidates = data.get("candidates", []) or []
        parts = (
            candidates[0].get("content", {}).get("parts", []) if candidates else []
        ) or []
        text_parts: list[str] = []
        tool_calls: list[ProviderToolCall] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            if "text" in part:
                text_parts.append(str(part.get("text", "")))
            elif "functionCall" in part:
                call = part.get("functionCall", {}) or {}
                tool_calls.append(
                    ProviderToolCall(
                        id=uuid4().hex,
                        name=str(call.get("name", "")),
                        arguments=dict(call.get("args", {}) or {}),
                    )
                )
        usage_raw = data.get("usageMetadata", {}) or {}
        usage = {
            "input_tokens": int(usage_raw.get("promptTokenCount", 0) or 0),
            "output_tokens": int(usage_raw.get("candidatesTokenCount", 0) or 0),
        }
        return AIProviderResult(
            text="".join(text_parts).strip(),
            tool_calls=tool_calls,
            usage=usage,
            provider=config.provider,
            model=config.model,
            stop_reason=str(candidates[0].get("finishReason", "")) if candidates else "",
        )


class FakeProviderClient:
    """Deterministic provider for tests and offline development.

    Protocol: the latest user message may contain a line of the form
    ``@tool <name> <json-args>``. On the first turn the fake client emits that
    tool call; once a tool result is present in the conversation it returns a
    final text answer so the orchestration loop terminates.
    """

    name = "fake"

    def complete(
        self,
        *,
        config: ResolvedAIProviderConfig,
        system_prompt: str,
        messages: list[ConversationMessage],
        tools: list[dict[str, Any]],
    ) -> AIProviderResult:
        executed = [m for m in messages if m.role == "tool"]
        directive = self._latest_directive(messages)
        if directive is not None and not executed:
            name, arguments = directive
            return AIProviderResult(
                text="",
                tool_calls=[ProviderToolCall(id=uuid4().hex, name=name, arguments=arguments)],
                usage={"input_tokens": 0, "output_tokens": 0},
                provider=config.provider,
                model=config.model,
                stop_reason="tool_use",
            )
        if executed:
            names = ", ".join(sorted({m.tool_name for m in executed if m.tool_name}))
            text = f"Fake provider completed after running tools: {names}."
        else:
            last_user = next(
                (m.content for m in reversed(messages) if m.role == "user"), ""
            )
            text = f"Fake provider received: {last_user}".strip()
        return AIProviderResult(
            text=text,
            tool_calls=[],
            usage={"input_tokens": 0, "output_tokens": 0},
            provider=config.provider,
            model=config.model,
            stop_reason="end_turn",
        )

    @staticmethod
    def _latest_directive(
        messages: list[ConversationMessage],
    ) -> tuple[str, dict[str, Any]] | None:
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        for line in last_user.splitlines():
            stripped = line.strip()
            if not stripped.startswith("@tool "):
                continue
            remainder = stripped[len("@tool ") :].strip()
            name, _, raw_args = remainder.partition(" ")
            try:
                arguments = json.loads(raw_args) if raw_args.strip() else {}
            except ValueError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            return name, arguments
        return None
