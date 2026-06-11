from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

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

# How often to emit a keepalive while the agent runs. A reverse/dev proxy (e.g.
# Next.js rewrites, ~30s idle timeout) aborts an upstream request that produces
# no bytes for too long; a sub-timeout heartbeat keeps the connection open for
# the full multi-step tool loop instead of surfacing an opaque 500.
_HEARTBEAT_SECONDS = 10.0


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


def _run_chat_turn(
    body: AIChatRequest, runtime: PipelineRuntime, admin: UserRecord
) -> dict:
    """Run one chat turn and return a JSON-able payload.

    All failure modes are captured into an ``{"error": {...}}`` payload rather
    than raised: the response is streamed, so once the 200 + headers are on the
    wire the status can no longer change. The client turns an ``error`` payload
    back into a thrown error, preserving the original messages and status codes.
    """
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
            return _error_payload(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "AI provider rate limit reached (input tokens per minute). "
                "Wait about a minute and retry. If it persists, lower "
                "max_tool_iterations in configs/app_config.yaml or request a "
                "higher limit from the provider.",
            )
        return _error_payload(status.HTTP_400_BAD_REQUEST, message)
    except ValueError as exc:
        return _error_payload(
            status.HTTP_400_BAD_REQUEST, redact_provider_error(str(exc), settings.ai)
        )
    except TimeoutError as exc:
        return _error_payload(status.HTTP_504_GATEWAY_TIMEOUT, str(exc))
    except Exception as exc:  # noqa: BLE001 - report a readable error, never crash the stream
        return _error_payload(
            status.HTTP_502_BAD_GATEWAY,
            f"AI chat failed: {redact_provider_error(str(exc), settings.ai)}",
        )
    return AIChatResponse(
        message={"role": "assistant", "content": outcome.text},
        tool_calls=[AIToolCallRecord(**asdict(call)) for call in outcome.tool_calls],
        drafts=[AIArtifactDraft(**draft) for draft in outcome.drafts],
        needs_confirmation=(
            AIToolCallRecord(**asdict(outcome.needs_confirmation))
            if outcome.needs_confirmation
            else None
        ),
    ).model_dump(mode="json")


def _error_payload(status_code: int, detail: str) -> dict:
    return {"error": {"status": status_code, "detail": detail}}


# Streaming handler: the agent's blocking tool loop runs in a worker thread while
# this coroutine emits a keepalive heartbeat every few seconds. That keeps the
# fronting proxy's idle timer from aborting a long turn (which otherwise surfaces
# as an opaque 500). The body is newline-delimited: zero or more blank heartbeat
# lines followed by a single JSON result/error line (the client parses the last
# non-empty line). Auth failures still surface as a normal 401/403 because the
# dependencies run before streaming begins.
@router.post("/messages")
async def send_ai_chat_message(
    body: AIChatRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    admin: Annotated[UserRecord, Depends(require_admin)],
) -> StreamingResponse:
    async def _stream():
        task = asyncio.create_task(asyncio.to_thread(_run_chat_turn, body, runtime, admin))
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=_HEARTBEAT_SECONDS)
                if task in done:
                    exc = task.exception()
                    if exc is not None:
                        payload = _error_payload(
                            status.HTTP_502_BAD_GATEWAY,
                            f"AI chat failed: {redact_provider_error(str(exc), settings.ai)}",
                        )
                    else:
                        payload = task.result()
                    yield (json.dumps(payload) + "\n").encode("utf-8")
                    return
                # Keepalive: a bare newline resets the proxy idle timer without
                # disturbing the final JSON line.
                yield b"\n"
        except asyncio.CancelledError:
            task.cancel()
            raise

    return StreamingResponse(_stream(), media_type="application/x-ndjson")
