from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime, require_admin
from app.core.config import settings
from app.schemas.ai_chat import (
    AIArtifactDraft,
    AIChatRequest,
    AIChatResponse,
    AIContextResponse,
    AIProviderSelection,
    AIProviderTestResponse,
    AISchemaBundleResponse,
    AIToolCallRecord,
    AIToolExecuteRequest,
)
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.ai_agent import AIChatAgent
from bio_pipeline_manager.ai_providers import (
    AIProviderError,
    provider_statuses,
    provider_test_result,
    redact_provider_error,
)
from bio_pipeline_manager.ai_schema_provider import AISchemaProvider
from bio_pipeline_manager.ai_tools import AIToolRegistry
from bio_pipeline_manager.auth_models import UserRecord


router = APIRouter(prefix="/ai-chat", tags=["ai-chat"])


def _context_path() -> Path:
    return Path(__file__).resolve().parents[4] / "docs" / "AI_PIPELINE_DESIGNER_CONTEXT.md"


def _load_context_markdown() -> str:
    path = _context_path()
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _tool_registry(runtime: PipelineRuntime, admin: UserRecord) -> AIToolRegistry:
    return AIToolRegistry(runtime, actor=admin.id)


def _schema_provider(runtime: PipelineRuntime, admin: UserRecord) -> AISchemaProvider:
    return AISchemaProvider(
        api_prefix=settings.api_prefix,
        tool_definitions=_tool_registry(runtime, admin).definitions(),
        context_path=_context_path(),
    )


@router.get("/context", response_model=AIContextResponse)
async def get_ai_context(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    admin: Annotated[UserRecord, Depends(require_admin)],
) -> AIContextResponse:
    schema = _schema_provider(runtime, admin).build_bundle()
    ai_config = settings.ai
    return AIContextResponse(
        context=_load_context_markdown(),
        default_provider=str(ai_config.get("default_provider", "claude")),
        providers=[asdict(status) for status in provider_statuses(ai_config)],
        max_tool_iterations=int(ai_config.get("max_tool_iterations", 8)),
        schema_digest=schema.digest,
        tools=_tool_registry(runtime, admin).definitions(),
    )


@router.get("/schema", response_model=AISchemaBundleResponse)
async def get_ai_schema(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    admin: Annotated[UserRecord, Depends(require_admin)],
) -> AISchemaBundleResponse:
    return AISchemaBundleResponse(**asdict(_schema_provider(runtime, admin).build_bundle()))


@router.post("/test-provider", response_model=AIProviderTestResponse)
async def test_ai_provider(body: AIProviderSelection) -> AIProviderTestResponse:
    try:
        result = provider_test_result(
            settings.ai,
            provider=body.provider,
            model=body.model,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=redact_provider_error(str(exc), settings.ai),
        ) from exc
    return AIProviderTestResponse(**result)


# Sync: confirmed tools may submit/run jobs (blocking). Runs in a threadpool.
@router.post("/tools/execute", response_model=AIToolCallRecord)
def execute_ai_tool(
    body: AIToolExecuteRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    admin: Annotated[UserRecord, Depends(require_admin)],
) -> AIToolCallRecord:
    execution = _tool_registry(runtime, admin).execute(
        body.name,
        body.arguments,
        confirmed=body.confirmed,
    )
    return AIToolCallRecord(**asdict(execution))


# Sync handler: the agent loop makes blocking httpx provider calls. FastAPI runs
# a sync def in a threadpool, so the multi-second tool loop never stalls the
# event loop (which would starve other requests and reset proxied connections).
@router.post("/messages", response_model=AIChatResponse)
def send_ai_chat_message(
    body: AIChatRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    admin: Annotated[UserRecord, Depends(require_admin)],
) -> AIChatResponse:
    agent = AIChatAgent(
        registry=_tool_registry(runtime, admin),
        schema_provider=_schema_provider(runtime, admin),
        context_markdown=_load_context_markdown(),
        ai_config=settings.ai,
        api_prefix=settings.api_prefix,
    )
    try:
        outcome = agent.run(
            messages=body.messages,
            selection=body.provider,
            confirmations=body.confirmations,
            active_pipeline_yaml=body.active_pipeline_yaml,
            active_job_definition=body.active_job_definition,
        )
    except AIProviderError as exc:
        message = redact_provider_error(str(exc), settings.ai)
        if "429" in message or "rate_limit" in message:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "AI provider rate limit reached (input tokens per minute). "
                    "Wait about a minute and retry. If it persists, lower "
                    "max_tool_iterations in configs/app_config.yaml or request a "
                    "higher limit from the provider."
                ),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=message
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=redact_provider_error(str(exc), settings.ai),
        ) from exc
    except Exception as exc:  # noqa: BLE001 - return a readable error, never a bare 500
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI chat failed: {redact_provider_error(str(exc), settings.ai)}",
        ) from exc
    return AIChatResponse(
        message={"role": "assistant", "content": outcome.text},
        tool_calls=[AIToolCallRecord(**asdict(call)) for call in outcome.tool_calls],
        drafts=[AIArtifactDraft(**draft) for draft in outcome.drafts],
        needs_confirmation=(
            AIToolCallRecord(**asdict(outcome.needs_confirmation))
            if outcome.needs_confirmation
            else None
        ),
    )
