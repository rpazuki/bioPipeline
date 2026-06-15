from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AIProvider = Literal["claude", "openai", "gemini", "openai_compatible", "fake"]


class AIProviderSelection(BaseModel):
    provider: AIProvider | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class AIProviderStatus(BaseModel):
    provider: str
    enabled: bool
    configured: bool
    model: str = ""
    base_url: str = ""
    is_default: bool = False


class AIProviderTestResponse(BaseModel):
    ok: bool
    provider: str
    model: str = ""
    message: str


class AIChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AIToolExecuteRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False


class AIToolCallRecord(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending_confirmation", "running", "succeeded", "failed", "skipped"]
    result: dict[str, Any] | None = None
    error: str | None = None
    requires_confirmation: bool = False


class AIArtifactDraft(BaseModel):
    kind: Literal["pipeline_yaml", "job_definition", "published_job"]
    name: str = ""
    content: str | dict[str, Any] | list[Any]
    source: Literal["model", "tool"] = "model"


class AIChatRequest(BaseModel):
    provider: AIProviderSelection = Field(default_factory=AIProviderSelection)
    messages: list[AIChatMessage]
    active_pipeline_yaml: str = ""
    active_job_definition: str = ""
    active_published_job: str = ""
    confirmations: dict[str, bool] = Field(default_factory=dict)
    requested_tools: list[AIToolExecuteRequest] = Field(default_factory=list)


class AIChatResponse(BaseModel):
    message: AIChatMessage
    tool_calls: list[AIToolCallRecord] = Field(default_factory=list)
    drafts: list[AIArtifactDraft] = Field(default_factory=list)
    needs_confirmation: AIToolCallRecord | None = None


class AIContextResponse(BaseModel):
    context: str
    default_provider: str
    providers: list[AIProviderStatus]
    max_tool_iterations: int
    schema_digest: str
    tools: list[dict[str, Any]]


class AISchemaBundleResponse(BaseModel):
    version: str
    generated_at: str
    digest: str
    pipeline_yaml: dict[str, Any]
    job_definition: dict[str, Any]
    published_job: dict[str, Any]
    api_tools: list[dict[str, Any]]
    examples: dict[str, str]
    notes: list[str]
