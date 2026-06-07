# AI Agent Admin Chat Plan

Last updated: 2026-06-07

Status: planning only. This document describes the planned AI chat/admin agent
feature. Parts that mention Published Jobs are superseded: **publishing was
removed from the AI process.** The agent now only designs, validates, and saves
Pipeline YAML and Job Definition YAML. Creating and publishing Published Jobs is
a manual admin task on the Job Publishing page. The live guide is
`docs/AI_PIPELINE_DESIGNER_CONTEXT.md`.

## Goal

Add an admin-only AI chat page that helps design, validate, save, submit, and
publish Bio Pipeline Manager workflow artifacts from a user's natural language
description.

The agent's purpose is narrow:

- Design lower-level pipeline YAML.
- Design higher-level Job Definition YAML.
- Preview and validate Job Definitions before queue submission.
- Create draft Published Jobs from Job Definitions.
- Publish Published Jobs only after explicit admin confirmation.

The default provider is Claude. Provider credentials and model defaults live in
`configs/app_config.yaml`; admins should not need to paste an API key into the
chat page on every session.

## Non-Goals

- Do not let ordinary users access the AI designer page.
- Do not run arbitrary shell commands from the model.
- Do not install packages from the chat in the first version.
- Do not ask admins to enter provider API keys in the browser.
- Do not expose configured provider API keys to the frontend.
- Do not publish or submit jobs without an explicit admin confirmation step.
- Do not let the model write directly to the filesystem outside existing project
  storage APIs.

## Existing Project Context

The feature should reuse the current project boundaries.

- Frontend: `frontend/src/app` and `frontend/src/components/pipelines`.
- Typed frontend API client: `frontend/src/lib/api.ts`.
- Shared frontend types: `frontend/src/types/index.ts`.
- Backend app assembly: `backend/app/main.py`.
- Backend routes: `backend/app/api/routes`.
- Backend schemas: `backend/app/schemas/pipelines.py`.
- Runtime wiring: `backend/app/services/runtime.py`.
- Shared domain logic: `src/bio_pipeline_manager`.
- Pipeline YAML validation: `src/bio_pipeline_manager/yaml_validation.py`.
- Job Definition parsing and expansion: `src/bio_pipeline_manager/job_definition.py`.
- Published Job inspection/rendering: `src/bio_pipeline_manager/published_jobs.py`.

Relevant existing admin APIs:

- `GET /api/v1/runtime`
- `GET /api/v1/pipeline-yamls`
- `GET /api/v1/pipeline-yamls/{name}`
- `POST /api/v1/pipeline-yamls`
- `POST /api/v1/validation/yaml`
- `GET /api/v1/validation/pipeline-yamls/{name}`
- `GET /api/v1/job-definition-store`
- `GET /api/v1/job-definition-store/{name}`
- `POST /api/v1/job-definition-store`
- `POST /api/v1/job-definitions/preview`
- `POST /api/v1/job-definitions`
- `POST /api/v1/published-jobs/admin/inspect`
- `POST /api/v1/published-jobs/admin`
- `POST /api/v1/published-jobs/admin/{id}/publish`
- `POST /api/v1/published-jobs/admin/{id}/validate`

All AI backend routes should use the same admin auth boundary as the current
admin APIs.

## User Workflow

1. Admin opens `/ai-chat`.
2. Page defaults to provider `claude`.
3. The page shows configured provider/model status and optionally lets the admin
   select among enabled providers.
4. Admin describes the desired workflow in natural language.
5. The agent reads available project context through safe API tools:
   existing pipeline YAMLs, stored Job Definitions, runtime paths, templates,
   validation reports, and published-job field candidates.
6. The agent drafts one or more artifacts:
   pipeline YAML, Job Definition YAML, and optional Published Job fields.
7. The backend runs validation/preview tools and returns structured results.
8. The frontend shows:
   chat response, tool trace, YAML draft, validation report, and previewed tasks.
9. Admin can save drafts to project storage.
10. Admin can create a Published Job as draft.
11. Admin can publish only after an explicit confirmation action.

## Frontend Plan

Create a new app route:

```text
frontend/src/app/ai-chat/page.tsx
```

Add navigation in:

```text
frontend/src/components/pipelines/AppShell.tsx
```

Suggested nav label:

```text
AI Designer
```

The page should be admin-only by inheritance from `AuthGate`. No ordinary-user
route exception should be added.

### Layout

Use the existing quiet operational style:

- Full-width admin workspace with `p-5`.
- Dense panels, not a marketing page.
- 8px-or-less radii, matching current `rounded-md` pattern.
- No nested cards.
- No decorative gradient/orb backgrounds.

Recommended layout:

```text
+-----------------------------------------------------------------------+
| Provider controls: configured provider, model, status, test            |
+-----------------------------+--------------------+--------------------+
| Chat thread                 | Draft editor       | Context/tools      |
| - messages                  | - Pipeline YAML    | - available YAMLs  |
| - tool call trace           | - Job Definition   | - validation       |
| - confirmations             | - Published fields | - preview tasks    |
+-----------------------------+--------------------+--------------------+
| Action bar: Validate, Preview, Save, Create Draft, Publish             |
+-----------------------------------------------------------------------+
```

### Frontend State

Track:

- `availableProviders`: configured provider metadata with no secrets.
- `provider`: currently selected configured provider.
- `model`: provider-specific model label returned by the backend.
- `messages`: chat transcript.
- `draftPipelineYaml`: string.
- `draftJobDefinition`: string.
- `draftPublishedFields`: `PublishedField[]`.
- `validationReport`: `ValidationReport | null`.
- `jobPreview`: `JobDefinitionPreview | null`.
- `pendingConfirmation`: high-impact tool call awaiting admin approval.
- `status`: short operation status.
- `error`: user-facing error.

### Frontend Components

Keep the first implementation local to the page unless the file becomes too
large. Extract when needed:

```text
frontend/src/components/pipelines/AIProviderPanel.tsx
frontend/src/components/pipelines/AIChatThread.tsx
frontend/src/components/pipelines/AIDraftWorkspace.tsx
frontend/src/components/pipelines/AIToolTrace.tsx
frontend/src/components/pipelines/AIConfirmationBar.tsx
```

### Frontend API Helpers

Add typed helpers to `frontend/src/lib/api.ts`:

- `sendAIChatMessage(payload)`
- `testAIProvider(payload)`
- `getAIContextSummary()`

Add types to `frontend/src/types/index.ts`:

- `AIProvider`
- `AIProviderStatus`
- `AIProviderSelection`
- `AIChatMessage`
- `AIChatRequest`
- `AIChatResponse`
- `AIToolCall`
- `AIToolResult`
- `AIArtifactDraft`
- `AIConfirmationRequest`

## Backend Plan

Create route module:

```text
backend/app/api/routes/ai_chat.py
```

Register it in:

```text
backend/app/main.py
```

with admin-only dependencies:

```python
app.include_router(ai_chat.router, prefix=PREFIX, dependencies=ADMIN_ONLY)
```

Create schemas:

```text
backend/app/schemas/ai_chat.py
```

Create shared service modules:

```text
src/bio_pipeline_manager/ai_agent.py
src/bio_pipeline_manager/ai_providers.py
src/bio_pipeline_manager/ai_schema_provider.py
src/bio_pipeline_manager/ai_tools.py
```

The backend should mediate every provider call. The browser should never call
Anthropic/OpenAI/Gemini APIs directly and should never receive configured API
keys.

### Backend Routes

Recommended initial routes:

```text
GET  /api/v1/ai-chat/context
GET  /api/v1/ai-chat/schema
POST /api/v1/ai-chat/test-provider
POST /api/v1/ai-chat/tools/execute
POST /api/v1/ai-chat/messages
```

Optional later routes:

```text
POST /api/v1/ai-chat/sessions
GET  /api/v1/ai-chat/sessions/{id}
POST /api/v1/ai-chat/sessions/{id}/messages
DELETE /api/v1/ai-chat/sessions/{id}
```

Do not add session persistence in the first version unless the UI clearly needs
conversation history after reload.

### Request Shape

Representative Pydantic shape:

```python
class AIProviderSelection(BaseModel):
    provider: Literal["claude", "openai", "gemini", "openai_compatible"] | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class AIChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AIChatRequest(BaseModel):
    provider: AIProviderSelection = Field(default_factory=AIProviderSelection)
    messages: list[AIChatMessage]
    active_pipeline_yaml: str = ""
    active_job_definition: str = ""
    active_published_fields: list[PublishedField] = Field(default_factory=list)
    confirmations: dict[str, bool] = Field(default_factory=dict)
```

Representative response:

```python
class AIArtifactDraft(BaseModel):
    kind: Literal["pipeline_yaml", "job_definition", "published_fields"]
    name: str = ""
    content: str | dict | list
    source: Literal["model", "tool"] = "model"


class AIToolCallRecord(BaseModel):
    id: str
    name: str
    arguments: dict
    status: Literal["pending_confirmation", "running", "succeeded", "failed", "skipped"]
    result: dict | None = None
    error: str | None = None


class AIChatResponse(BaseModel):
    message: AIChatMessage
    tool_calls: list[AIToolCallRecord] = Field(default_factory=list)
    drafts: list[AIArtifactDraft] = Field(default_factory=list)
    validation: ValidationReportResponse | None = None
    preview: JobDefinitionPreviewResponse | None = None
    needs_confirmation: AIToolCallRecord | None = None
```

## Provider Abstraction

Use one internal interface:

```python
class AIProviderClient(Protocol):
    def complete(
        self,
        *,
        config: ResolvedAIProviderConfig,
        system_prompt: str,
        messages: list[AIChatMessage],
        tools: list[AIToolDefinition],
    ) -> AIProviderResult: ...
```

Normalize provider output into:

- assistant text
- tool calls
- token usage, when available
- raw provider name/model

Initial provider adapters:

- `ClaudeProviderClient`
- `OpenAIProviderClient`
- `GeminiProviderClient`
- `OpenAICompatibleProviderClient`

Implementation choice:

- Prefer direct HTTP with `httpx` to avoid adding several SDK dependencies.
- If SDKs are added later, keep them behind the same provider interface.

Suggested dependency:

```toml
httpx>=0.27.0
```

`httpx` is already present in dev dependencies, but the backend runtime package
should include it if provider calls are implemented with HTTP.

## Provider Defaults

The page should default to:

```text
provider: claude
model: configured default from backend settings
```

Provider credentials and defaults are configured in `configs/app_config.yaml`,
not entered in the browser:

```yaml
backend:
  shared:
    ai:
      default_provider: claude
      max_tool_iterations: 8
      providers:
        claude:
          enabled: true
          api_key: ""
          model: ""
          base_url: https://api.anthropic.com
        openai:
          enabled: false
          api_key: ""
          model: ""
          base_url: https://api.openai.com/v1
        gemini:
          enabled: false
          api_key: ""
          model: ""
          base_url: https://generativelanguage.googleapis.com
        openai_compatible:
          enabled: false
          api_key: ""
          model: ""
          base_url: ""
```

Leave model values blank if deployment should fail fast until an operator
chooses a current model. This avoids hard-coding provider model names that age
quickly.

The backend should expose only non-secret provider metadata to the frontend:

```json
{
  "default_provider": "claude",
  "providers": [
    {"provider": "claude", "enabled": true, "configured": true, "model": "..."}
  ]
}
```

`configured` means an API key is present server-side. The key value itself is
never returned.

## Schema Provider

Add a backend schema provider so the chat can understand current project schemas
deeply and adapt as the code changes.

Create:

```text
src/bio_pipeline_manager/ai_schema_provider.py
```

Purpose:

- Produce a machine-readable schema bundle for the AI agent.
- Use current backend/domain code as the source of truth where possible.
- Reduce duplicated, stale schema prose inside prompts.
- Give provider adapters a compact schema payload for tools and structured
  output.

The schema provider should collect:

- Pydantic JSON schemas from `backend/app/schemas/pipelines.py`.
- Tool argument schemas from `src/bio_pipeline_manager/ai_tools.py`.
- Job Definition structural rules from `src/bio_pipeline_manager/job_definition.py`.
- Pipeline YAML validation rules from
  `src/bio_pipeline_manager/yaml_validation.py`.
- Published Job field types and binding targets from
  `src/bio_pipeline_manager/published_jobs.py`.
- Current API prefix and route summaries from backend settings.
- Example fragments from `docs/AI_PIPELINE_DESIGNER_CONTEXT.md`.

Recommended interface:

```python
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
    def build_bundle(self) -> AISchemaBundle: ...
    def build_prompt_context(self) -> str: ...
```

The `digest` should be stable for the same schema content. The frontend can show
it as "schema context version", and tests can assert that meaningful schema
changes update the bundle.

Expose it through:

```text
GET /api/v1/ai-chat/schema
```

The chat orchestrator should include both:

- Static guidance from `docs/AI_PIPELINE_DESIGNER_CONTEXT.md`.
- Dynamic schema bundle from `AISchemaProvider`.

The model should treat the schema bundle as authoritative when it conflicts with
older examples or prose.

## Tool Execution Model

The model can request tools, but only the backend executes them. Each tool wraps
existing project services or routes.

### Read-Only Tools

These can run automatically:

```text
get_runtime_info
list_pipeline_yamls
get_pipeline_yaml
list_job_definitions
get_job_definition
list_published_jobs_admin
validate_pipeline_yaml
preview_job_definition
inspect_published_job_fields
```

### Write Tools

These can run automatically only when the result is a draft and reversible:

```text
save_pipeline_yaml
save_job_definition
create_published_job_draft
```

Even for these, the frontend should show the target name/path before execution
when possible.

### High-Impact Tools

These require explicit admin confirmation:

```text
submit_job_definition
publish_published_job
archive_published_job
delete_published_job
run_due_jobs
install_package
uninstall_package
```

For the first version, do not expose package install/uninstall tools to the
model.

## Initial Tool Catalog

The backend should define the model-callable tools with JSON schemas.

### `list_pipeline_yamls`

Purpose: list stored pipeline YAML documents and their pipeline names.

Returns:

```json
{
  "items": [
    {"name": "growth_rates_pipeline.yaml", "pipelines": ["growth_rate_fit_pipeline"], "is_valid": true}
  ]
}
```

### `get_pipeline_yaml`

Arguments:

```json
{"name": "growth_rates_pipeline.yaml"}
```

Returns the stored YAML content and summary.

### `validate_pipeline_yaml`

Arguments:

```json
{"content": "...", "imports": false}
```

Uses `validate_labutils_yaml`. The agent should call this before saving or
referencing a newly drafted pipeline YAML.

### `save_pipeline_yaml`

Arguments:

```json
{"name": "folder/name.yaml", "content": "...", "overwrite": true}
```

Uses `YamlStore.save` through the existing API/service path.

### `list_job_definitions`

Returns saved Job Definition summaries.

### `get_job_definition`

Arguments:

```json
{"name": "growth_full.yaml"}
```

Returns content and validation status from `JobDefinitionStore`.

### `save_job_definition`

Arguments:

```json
{"name": "growth_full.yaml", "content": "...", "overwrite": true}
```

Uses existing Job Definition store validation.

### `preview_job_definition`

Arguments:

```json
{"content": "..."}
```

Uses `expand(content, lenient=True)` through the existing preview route/service.

### `inspect_published_job_fields`

Arguments:

```json
{"content": "..."}
```

Uses `inspect_definition` to generate candidate Published Job form fields.

### `create_published_job_draft`

Arguments:

```json
{
  "name": "Growth Rate Analysis",
  "description": "User-facing growth rate pipeline.",
  "definition_name": "growth_full.yaml",
  "definition_content": "...",
  "fields": []
}
```

Always creates `status: draft` in the first version.

### `publish_published_job`

Arguments:

```json
{"published_job_id": "..."}
```

Requires explicit confirmation. Before executing, the backend should validate
the saved published job.

## Context Markdown Plan

Create a second context document for the model:

```text
docs/AI_PIPELINE_DESIGNER_CONTEXT.md
```

This file should be loaded into the AI system prompt by the backend. It should
be maintained as the stable instruction/context source for the agent. Dynamic
schema details should come from `AISchemaProvider`, not from hand-copied schema
text alone.

Suggested sections:

1. Mission
   - The agent designs Bio Pipeline Manager artifacts only.
   - It should ask clarifying questions when scientific intent is ambiguous.
   - It should validate before claiming success.

2. Project Architecture
   - Frontend, backend, shared domain layer.
   - Runtime state layout.
   - Admin auth boundary.

3. Pipeline YAML Schema
   - Top-level `pipelines` list.
   - One-item mapping for each pipeline.
   - Required sections: `Inputs`, `Processes`, `Outputs`.
   - Input shape and required `src`, `package`, `method`.
   - Process shape and required `package`, `method`, `parameters`.
   - Output shape and path rules.
   - Payload reference warnings.

4. Job Definition Schema
   - Required `job`.
   - Optional `description`.
   - Optional `variables`, each as non-empty list.
   - Optional `defaults`.
   - Required non-empty `stages`.
   - Required stage keys: `name`, `pipeline_yaml`, `pipeline`, `output_dir`.
   - Optional stage keys: `needs`, `fanout`, `input_sources`,
     `input_arg_mapping`, `process_arg_mapping`, `output_path_mapping`.
   - Fanout types: `none`, `mapping_file`, `patterns`, `folders`.
   - Template tokens: matrix variables, dict variable fields, defaults,
     `data_dir`, `item.raw`, `item.meta`, `item.stem`, `item.name`,
     `item.path`.

5. Published Job Schema
   - Draft/published/archive lifecycle.
   - Field types.
   - Field bindings.
   - Required field IDs and bindings.
   - Public fields must not expose bindings.

6. Tool Rules
   - Read tools may be used proactively.
   - Save tools should produce named drafts.
   - Submit/publish tools need confirmation.
   - Never hallucinate successful saves or publishes.

7. Design Heuristics
   - Prefer reusing existing stored pipeline YAML when possible.
   - If a requested process package/method does not exist in context, mark it
     as an assumption and ask the admin.
   - Generate minimal valid YAML first, then iterate from validation errors.
   - For user-facing Published Jobs, expose only necessary fields.
   - Use clear names for jobs, stages, variables, and fields.

8. Examples
   - Minimal pipeline YAML.
   - Minimal single-stage Job Definition.
   - Multi-stage preprocess -> collate Job Definition.
   - Published Job field binding examples.

The context file should summarize `docs/JOBS.md` and project API routes, not
copy every line. The backend can include it in the system prompt alongside a
short current runtime summary and the dynamic schema bundle.

## System Prompt Shape

The backend should build a system prompt like:

```text
You are the Bio Pipeline Manager AI Designer.
You help admins design pipeline YAML, Job Definition YAML, and Published Jobs.
Use tools to inspect existing YAML and validate drafts before finalizing.
Never submit or publish without explicit admin confirmation.

<project_context>
...contents of docs/AI_PIPELINE_DESIGNER_CONTEXT.md...
</project_context>

<current_runtime>
api_prefix: /api/v1
available_tools: ...
</current_runtime>

<schema_bundle>
...current AISchemaProvider bundle...
</schema_bundle>
```

The prompt should be provider-neutral. Provider adapters should translate it to
the provider's expected API shape.

## Security Plan

API keys:

- Read provider API keys from backend configuration under
  `backend.shared.ai.providers`.
- Do not request API keys in the frontend.
- Do not send API keys from the frontend.
- Do not return API keys from `/api/v1/ai-chat/context` or
  `/api/v1/ai-chat/schema`.
- Do not log provider API keys.
- Redact API keys from exceptions.
- Prefer an untracked deployment config via `APP_CONFIG_PATH` for real secrets
  if the repository is shared.

Auth:

- All AI routes require admin.
- Ordinary users cannot access `/ai-chat`.

Tool safety:

- Use an allowlist of tools.
- Validate tool arguments with Pydantic before execution.
- Route write tools through existing stores/services.
- Block path traversal by relying on existing store path validation.
- Require confirmation for submit/publish/archive/delete/run/install tools.

Provider safety:

- Set request timeouts.
- Set response size limits.
- Surface provider errors without raw secret-bearing request data.
- Avoid sending job logs unless the admin explicitly includes them.

Audit:

- First version can rely on existing storage history.
- Later version should add an AI action audit table with admin user, timestamp,
  provider, model, tool calls, target artifact names, and confirmation outcomes.

## Validation Rules

The agent should follow this sequence for pipeline YAML:

1. Draft YAML.
2. Call `validate_pipeline_yaml`.
3. Fix validation errors.
4. Save only when valid or when admin explicitly asks to save an invalid draft.

The agent should follow this sequence for Job Definitions:

1. Inventory relevant stored pipeline YAMLs.
2. Draft Job Definition.
3. Call `preview_job_definition`.
4. Fix structural/template errors.
5. Save only after preview succeeds or admin explicitly asks to save a draft.
6. Submit only after admin confirmation.

The agent should follow this sequence for Published Jobs:

1. Start from valid Job Definition content.
2. Call `inspect_published_job_fields`.
3. Select a small set of necessary public fields.
4. Create as draft.
5. Validate saved draft.
6. Publish only after admin confirmation.

## Implementation Phases

### Phase 1: Documentation and Context

- Add this planning doc.
- Add `docs/AI_PIPELINE_DESIGNER_CONTEXT.md`.
- Add placeholder AI provider config to `configs/app_config.yaml`.
- Keep the context file aligned with `docs/JOBS.md`, `docs/PROJECT_OVERVIEW.md`,
  and current API schemas.
- Plan the dynamic schema-provider bundle that will become the backend source of
  truth for AI schema context.

### Phase 2: Backend Skeleton

- Add `backend/app/schemas/ai_chat.py`.
- Add `backend/app/api/routes/ai_chat.py`.
- Register the router in `backend/app/main.py`.
- Add read-only context endpoint.
- Add read-only schema endpoint backed by `AISchemaProvider`.
- Add provider test endpoint with fake-provider support for tests.
- Add direct tool execution endpoint for the admin UI and backend tests.

### Phase 3: Tool Layer

- Add `src/bio_pipeline_manager/ai_tools.py`.
- Implement read-only tools first.
- Add save/draft tools after read-only tests pass.
- Add confirmation-gated high-impact tool support.

### Phase 4: Provider Layer

- Add `src/bio_pipeline_manager/ai_providers.py`.
- Implement provider interface.
- Implement Claude first.
- Add OpenAI and Gemini after the tool loop is covered by tests.
- Add OpenAI-compatible adapter last.

### Phase 5: Frontend Page

- Add `/ai-chat` route.
- Add nav link.
- Add provider controls.
- Add chat thread and draft editor.
- Add tool trace and confirmation UI.
- Add validation/preview result panels.

### Phase 6: End-to-End Polish

- Add loading/error states.
- Add copy/download affordances for drafts if useful.
- Add validation badges.
- Add "created draft" deep links to existing Job Storage and Published Jobs
  Admin pages.
- Verify responsive layout.

## Test Plan

Backend tests:

- Admin auth is required for all `/ai-chat` routes.
- Non-admin users receive 403.
- Provider keys are read from backend config.
- Provider keys are never returned by context/schema endpoints.
- API keys are redacted from errors.
- Schema provider returns current Pydantic/tool/domain schema metadata.
- Fake provider can return assistant text.
- Fake provider can request read-only tools.
- Tool calls validate arguments.
- `validate_pipeline_yaml` returns existing validation shape.
- `preview_job_definition` returns existing preview shape.
- Save tools use existing stores.
- Submit/publish tools are blocked without confirmation.

Frontend tests:

- Provider panel defaults to Claude.
- Provider panel shows configured provider status without exposing keys.
- API key inputs are not rendered.
- Chat submit calls `sendAIChatMessage`.
- Tool calls render status and result.
- Confirmation UI appears for high-impact tools.
- Draft editor updates from AI response.
- Validation report renders errors/warnings.

Manual verification:

1. Start backend and frontend.
2. Log in as admin.
3. Open `/ai-chat`.
4. Confirm Claude is shown as the default configured provider.
5. Test provider connection.
6. Ask for a simple one-stage Job Definition based on an existing pipeline YAML.
7. Confirm the agent lists existing YAMLs.
8. Confirm preview succeeds.
9. Save the Job Definition draft.
10. Create a Published Job draft.
11. Confirm publish requires explicit approval.

## Open Questions

- Should real provider keys be stored directly in `configs/app_config.yaml`, or
  should deployments use a private `APP_CONFIG_PATH` file?
- Should conversation history persist in SQLite?
- Should the AI page be allowed to submit jobs, or only save/publish artifacts?
- Should the agent be able to read job logs for debugging failed runs?
- Should package installation become a tool later, behind a separate approval
  workflow?
- Which provider/model list should be exposed by default in production config?

## Acceptance Criteria

The feature is ready when:

- Admin can open `/ai-chat`.
- Claude is selected by default.
- Provider credentials are read from backend config.
- API keys are never exposed to the frontend.
- The backend exposes dynamic schema context through the schema provider.
- The agent can inspect existing pipeline YAML and Job Definition storage.
- The agent can draft valid Pipeline YAML and Job Definition YAML.
- The agent can validate pipeline YAML.
- The agent can preview Job Definitions.
- The agent can save drafts through existing project stores.
- The agent can create Published Job drafts.
- Publish requires explicit admin confirmation.
- Backend and frontend tests cover the tool loop and safety boundaries.
