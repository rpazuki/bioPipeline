import type {
  AIChatRequest,
  AIChatResponse,
  AIContextResponse,
  AIProviderSelection,
  AIProviderTestResponse,
  AIToolCallRecord,
  DefinitionDocument,
  DefinitionSummary,
  Job,
  JobDefinitionPreview,
  JobDefinitionTemplate,
  JobDefinitionTemplateSummary,
  JobGroupDetail,
  JobGroupSummary,
  JobSubmit,
  PackageList,
  PackageOpResult,
  PackageSourceType,
  PublishedField,
  PublishedJobAdmin,
  PublishedJobPublicDetail,
  PublishedJobPublicSummary,
  PublishedRunDetail,
  PublishedRunSummary,
  PipelineTemplate,
  PipelineTemplateSummary,
  RecurrenceEndMode,
  RecurrenceUnit,
  RecurringJob,
  RecurringSchedule,
  ResolvedType,
  RuntimeInfo,
  SavedTypedValue,
  SharedEntry,
  SharedRootInfo,
  TypeDef,
  TypeExtractResponse,
  AuthResponse,
  User,
  UserCreate,
  UserUpdate,
  ValidationReport,
  YamlDocument,
  YamlSummary,
  YamlTreeNode,
} from "@/types";

const API_PREFIX = process.env.NEXT_PUBLIC_API_PREFIX ?? "/api/v1";

// Most calls should fail fast rather than hang forever. A few are legitimately
// long (AI chat, package installs, run-due) and opt into a larger timeout or
// disable it with 0.
const DEFAULT_TIMEOUT_MS = 60_000;
// The AI agent runs a multi-step provider loop; allow comfortably beyond the
// backend's own time budget so the client only aborts on a true hang.
export const AI_CHAT_TIMEOUT_MS = 180_000;
// Browser event other components (AuthContext) listen for to drop back to the
// login screen the moment any request reports an expired/missing session.
export const UNAUTHORIZED_EVENT = "bio-pipeline:unauthorized";

function notifyUnauthorized() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
  }
}

function encodePath(path: string) {
  return path
    .split("/")
    .filter((part) => part.length > 0)
    .map((part) => encodeURIComponent(part))
    .join("/");
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  // Abort a stalled request so callers get a clear timeout instead of an
  // indefinite spinner. timeoutMs <= 0 disables the deadline.
  const controller = new AbortController();
  const timer = timeoutMs > 0 ? setTimeout(() => controller.abort(), timeoutMs) : null;
  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      credentials: "include",
      ...options,
      headers,
      signal: controller.signal,
    });
  } catch (cause) {
    if ((cause as { name?: string })?.name === "AbortError") {
      throw new Error(
        `Request timed out after ${Math.round(timeoutMs / 1000)}s — the server took too long to respond. Wait a moment and retry.`,
      );
    }
    throw cause;
  } finally {
    if (timer) clearTimeout(timer);
  }
  if (!response.ok) {
    // A 401 on any call but the login attempt itself means the session has
    // expired or been revoked. Notify the app so it returns to the login screen
    // instead of silently swallowing the failure in a background poll.
    if (response.status === 401 && path !== "/auth/login") {
      notifyUnauthorized();
    }
    const body = await response.json().catch(() => ({}));
    if (body?.detail) {
      throw new Error(body.detail);
    }
    // A 5xx with no JSON detail almost always comes from the Next.js dev rewrite
    // proxy, not FastAPI: the proxy aborts upstream requests after ~30s, so a
    // long AI turn surfaces here as an opaque 500 with a clean backend log.
    if (response.status >= 500) {
      throw new Error(
        `Server error ${response.status} with no response body — this usually means the dev proxy timed out the request to the backend (its limit is ~30s) or the backend restarted. Check the Next.js terminal for the underlying error.`,
      );
    }
    throw new Error(`API error ${response.status}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

// Storage
export async function getRuntimeInfo() {
  return apiFetch<RuntimeInfo>("/runtime");
}

// Auth
export async function login(username: string, password: string) {
  return apiFetch<AuthResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function logout() {
  return apiFetch<void>("/auth/logout", { method: "POST" });
}

export async function getCurrentUser() {
  return apiFetch<AuthResponse>("/auth/me");
}

export async function changePassword(currentPassword: string, newPassword: string) {
  return apiFetch<AuthResponse>("/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

export async function listUsers() {
  return apiFetch<User[]>("/users");
}

export async function createUser(payload: UserCreate) {
  return apiFetch<User>("/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateUser(userId: string, payload: UserUpdate) {
  return apiFetch<User>(`/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function resetUserPassword(userId: string, password: string) {
  return apiFetch<User>(`/users/${encodeURIComponent(userId)}/reset-password`, {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}

export async function enableUser(userId: string) {
  return apiFetch<User>(`/users/${encodeURIComponent(userId)}/enable`, { method: "POST" });
}

export async function disableUser(userId: string) {
  return apiFetch<User>(`/users/${encodeURIComponent(userId)}/disable`, { method: "POST" });
}

export async function listPipelineYamls() {
  return apiFetch<YamlSummary[]>("/pipeline-yamls");
}

export async function getPipelineYamlTree() {
  return apiFetch<YamlTreeNode[]>("/pipeline-yamls/tree");
}

export async function createYamlFolder(path: string) {
  return apiFetch<YamlTreeNode>("/pipeline-yamls/folders", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export async function deleteYamlFolder(path: string) {
  return apiFetch<void>(`/pipeline-yamls/folders/${encodePath(path)}`, {
    method: "DELETE",
  });
}

export async function movePipelineYaml(sourcePath: string, destinationPath: string) {
  return apiFetch<YamlDocument>("/pipeline-yamls/move", {
    method: "POST",
    body: JSON.stringify({ source_path: sourcePath, destination_path: destinationPath }),
  });
}

export async function getPipelineYaml(name: string) {
  return apiFetch<YamlDocument>(`/pipeline-yamls/${encodePath(name)}`);
}

export async function deletePipelineYaml(name: string) {
  return apiFetch<void>(`/pipeline-yamls/${encodePath(name)}`, {
    method: "DELETE",
  });
}

export async function savePipelineYaml(name: string, content: string, overwrite = true) {
  return apiFetch<YamlDocument>("/pipeline-yamls", {
    method: "POST",
    body: JSON.stringify({ name, content, overwrite }),
  });
}

// Validation
export async function validateYamlContent(content: string, imports = false) {
  return apiFetch<ValidationReport>("/validation/yaml", {
    method: "POST",
    body: JSON.stringify({ content, imports }),
  });
}

export async function validateStoredYaml(name: string, imports = false) {
  return apiFetch<ValidationReport>(
    `/validation/pipeline-yamls/${encodePath(name)}?imports=${imports ? "true" : "false"}`
  );
}

// Templates
export async function listPipelineTemplates() {
  return apiFetch<PipelineTemplateSummary[]>("/templates");
}

export async function getPipelineTemplate(name: string) {
  return apiFetch<PipelineTemplate>(`/templates/${encodeURIComponent(name)}`);
}

// Job Definition templates (starter scenarios for the Job Definitions page)
export async function listJobDefinitionTemplates() {
  return apiFetch<JobDefinitionTemplateSummary[]>("/job-definition-templates");
}

export async function getJobDefinitionTemplate(name: string) {
  return apiFetch<JobDefinitionTemplate>(`/job-definition-templates/${encodeURIComponent(name)}`);
}

// Execution
export async function listJobs() {
  return apiFetch<Job[]>("/jobs");
}

export async function submitJob(payload: JobSubmit) {
  return apiFetch<Job>("/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// Recurring jobs (admin) — repeat a plain job submission on an interval.
export interface RecurringJobCreate {
  job: JobSubmit;
  every_n: number;
  unit: RecurrenceUnit;
  ends_mode: RecurrenceEndMode;
  ends_count?: number;
  ends_at?: string | null;
  start_at?: string | null;
}

export async function createRecurringJob(payload: RecurringJobCreate) {
  return apiFetch<RecurringJob>("/jobs/schedules", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listRecurringJobs() {
  return apiFetch<RecurringJob[]>("/jobs/schedules");
}

export async function stopRecurringJob(id: string) {
  return apiFetch<RecurringJob>(`/jobs/schedules/${encodeURIComponent(id)}/stop`, { method: "POST" });
}

export async function deleteRecurringJob(id: string) {
  return apiFetch<void>(`/jobs/schedules/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function runDueJobs(parallel = 1) {
  // Runs jobs synchronously server-side; can outlast the default timeout.
  return apiFetch<Job[]>(`/jobs/run-due?parallel=${parallel}`, {
    method: "POST",
  }, 0);
}

export async function cancelJob(jobId: string) {
  return apiFetch<Job>(`/jobs/${jobId}/cancel`, {
    method: "POST",
  });
}

export async function deleteJob(jobId: string) {
  return apiFetch<void>(`/jobs/${jobId}`, {
    method: "DELETE",
  });
}

export async function rewindJob(jobId: string, scheduledAt: string | null = null) {
  return apiFetch<Job>(`/jobs/${jobId}/rewind`, {
    method: "POST",
    body: JSON.stringify({ scheduled_at: scheduledAt }),
  });
}

export async function getJobLogs(jobId: string) {
  return apiFetch<{ id: string; log: string }>(`/jobs/${jobId}/logs`);
}

// Job Definitions (multi-task)
export async function previewJobDefinition(content: string) {
  return apiFetch<JobDefinitionPreview>("/job-definitions/preview", {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export async function submitJobDefinition(content: string, scheduledAt: string | null = null) {
  return apiFetch<JobGroupDetail>("/job-definitions", {
    method: "POST",
    body: JSON.stringify({ content, scheduled_at: scheduledAt }),
  });
}

export async function listJobDefinitions() {
  return apiFetch<JobGroupSummary[]>("/job-definitions");
}

export async function getJobDefinition(parentJobId: string) {
  return apiFetch<JobGroupDetail>(`/job-definitions/${encodeURIComponent(parentJobId)}`);
}

// Published jobs
export async function inspectPublishedJob(content: string) {
  return apiFetch<{ job_name: string; candidates: PublishedField[]; warnings: string[] }>("/published-jobs/admin/inspect", {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export async function listAdminPublishedJobs() {
  return apiFetch<PublishedJobAdmin[]>("/published-jobs/admin");
}

export async function listAdminPublishedRuns() {
  return apiFetch<PublishedRunSummary[]>("/published-jobs/admin/runs");
}

export async function listAdminPublishedJobRuns(id: string) {
  return apiFetch<PublishedRunSummary[]>(`/published-jobs/admin/${encodeURIComponent(id)}/runs`);
}

export async function getAdminPublishedJob(id: string) {
  return apiFetch<PublishedJobAdmin>(`/published-jobs/admin/${encodeURIComponent(id)}`);
}

export async function createPublishedJob(payload: {
  name: string;
  description: string;
  definition_name?: string;
  definition_content: string;
  fields: PublishedField[];
  status?: "draft" | "published";
}) {
  return apiFetch<PublishedJobAdmin>("/published-jobs/admin", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updatePublishedJob(
  id: string,
  payload: Partial<{
    name: string;
    description: string;
    definition_name: string;
    definition_content: string;
    fields: PublishedField[];
  }>,
) {
  return apiFetch<PublishedJobAdmin>(`/published-jobs/admin/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function publishPublishedJob(id: string) {
  return apiFetch<PublishedJobAdmin>(`/published-jobs/admin/${encodeURIComponent(id)}/publish`, { method: "POST" });
}

export async function archivePublishedJob(id: string) {
  return apiFetch<PublishedJobAdmin>(`/published-jobs/admin/${encodeURIComponent(id)}/archive`, { method: "POST" });
}

export async function validatePublishedJob(id: string) {
  return apiFetch<{ is_valid: boolean; candidate_count: number; field_count: number; run_count: number; warnings: string[] }>(
    `/published-jobs/admin/${encodeURIComponent(id)}/validate`,
    { method: "POST" },
  );
}

export async function deletePublishedJob(id: string, force = false) {
  return apiFetch<void>(`/published-jobs/admin/${encodeURIComponent(id)}?force=${force ? "true" : "false"}`, {
    method: "DELETE",
  });
}

export async function listPublishedJobs() {
  return apiFetch<PublishedJobPublicSummary[]>("/published-jobs");
}

export async function getPublishedJob(id: string) {
  return apiFetch<PublishedJobPublicDetail>(`/published-jobs/catalog/${encodeURIComponent(id)}`);
}

export interface RunFileBinding {
  kind: "upload" | "shared";
  path: string;
  root?: string | null;
}

export async function listJobSharedRoots(id: string) {
  return apiFetch<SharedRootInfo[]>(`/published-jobs/catalog/${encodeURIComponent(id)}/shared-roots`);
}

export async function listAdminSharedRoots() {
  return apiFetch<SharedRootInfo[]>("/published-jobs/admin/shared-roots");
}

export async function browseSharedRoot(id: string, field: string, root: string, subpath: string) {
  const query = new URLSearchParams({ field, root, subpath });
  return apiFetch<{ root_id: string; subpath: string; entries: SharedEntry[] }>(
    `/published-jobs/catalog/${encodeURIComponent(id)}/browse?${query.toString()}`,
  );
}

export async function createDraftRun(id: string) {
  return apiFetch<{ workspace_id: string }>(
    `/published-jobs/catalog/${encodeURIComponent(id)}/runs/draft`,
    { method: "POST" },
  );
}

const UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024;

type UploadResult = { field_id: string; handle: string; filename: string; size: number };

// Streams a file to the server in chunks (resumable-friendly). `relpath`
// preserves a file's position within an uploaded folder.
export async function uploadRunInput(id: string, workspaceId: string, fieldId: string, file: File, relpath = "") {
  const baseUrl =
    `${API_PREFIX}/published-jobs/catalog/${encodeURIComponent(id)}/runs/` +
    `${encodeURIComponent(workspaceId)}/uploads/${encodeURIComponent(fieldId)}`;
  let offset = 0;
  let last: UploadResult | null = null;
  do {
    const slice = file.slice(offset, offset + UPLOAD_CHUNK_BYTES);
    const params = new URLSearchParams({ filename: file.name, offset: String(offset) });
    if (relpath) params.set("relpath", relpath);
    const response = await fetch(`${baseUrl}?${params.toString()}`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/octet-stream" },
      body: slice,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body?.detail ?? `Upload failed (${response.status})`);
    }
    last = (await response.json()) as UploadResult;
    offset += UPLOAD_CHUNK_BYTES;
  } while (offset < file.size);
  return last as UploadResult;
}

export function runArtifactUrl(runId: string) {
  return `${API_PREFIX}/published-jobs/my-runs/${encodeURIComponent(runId)}/artifact`;
}

export async function submitPublishedJobRun(
  id: string,
  values: Record<string, unknown>,
  scheduledAt: string | null = null,
  extra: { workspaceId?: string | null; fileBindings?: Record<string, RunFileBinding> } = {},
) {
  return apiFetch<PublishedRunDetail>(`/published-jobs/catalog/${encodeURIComponent(id)}/runs`, {
    method: "POST",
    body: JSON.stringify({
      values,
      scheduled_at: scheduledAt,
      workspace_id: extra.workspaceId ?? null,
      file_bindings: extra.fileBindings ?? {},
    }),
  });
}

export async function listMyPublishedRuns() {
  return apiFetch<PublishedRunSummary[]>("/published-jobs/my-runs");
}

export async function getMyPublishedRun(id: string) {
  return apiFetch<PublishedRunDetail>(`/published-jobs/my-runs/${encodeURIComponent(id)}`);
}

export async function cancelMyPublishedRun(id: string) {
  return apiFetch<PublishedRunDetail>(`/published-jobs/my-runs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
}

export async function deleteMyPublishedRun(id: string) {
  return apiFetch<void>(`/published-jobs/my-runs/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function rewindMyPublishedRun(id: string, scheduledAt: string | null = null) {
  return apiFetch<PublishedRunDetail>(`/published-jobs/my-runs/${encodeURIComponent(id)}/rewind`, {
    method: "POST",
    body: JSON.stringify({ scheduled_at: scheduledAt }),
  });
}

// Recurring schedules (researcher)
export interface RecurringScheduleCreate {
  values: Record<string, unknown>;
  file_bindings?: Record<string, RunFileBinding>;
  workspace_id?: string | null;
  every_n: number;
  unit: RecurrenceUnit;
  ends_mode: RecurrenceEndMode;
  ends_count?: number;
  ends_at?: string | null;
  start_at?: string | null;
}

export async function createRecurringSchedule(id: string, payload: RecurringScheduleCreate) {
  return apiFetch<RecurringSchedule>(`/published-jobs/catalog/${encodeURIComponent(id)}/schedules`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listMyRecurringSchedules() {
  return apiFetch<RecurringSchedule[]>("/published-jobs/my-schedules");
}

export async function stopRecurringSchedule(id: string) {
  return apiFetch<RecurringSchedule>(`/published-jobs/my-schedules/${encodeURIComponent(id)}/stop`, { method: "POST" });
}

export async function deleteRecurringSchedule(id: string) {
  return apiFetch<void>(`/published-jobs/my-schedules/${encodeURIComponent(id)}`, { method: "DELETE" });
}

// Job Definition store (saved/archived reusable definitions)
export async function listSavedDefinitions() {
  return apiFetch<DefinitionSummary[]>("/job-definition-store");
}

export async function listArchivedDefinitions() {
  return apiFetch<DefinitionSummary[]>("/job-definition-store/archived");
}

export async function getSavedDefinition(name: string) {
  return apiFetch<DefinitionDocument>(`/job-definition-store/${encodePath(name)}`);
}

export async function saveDefinition(name: string, content: string, overwrite = true) {
  return apiFetch<DefinitionDocument>("/job-definition-store", {
    method: "POST",
    body: JSON.stringify({ name, content, overwrite }),
  });
}

export async function deleteSavedDefinition(name: string, archived = false) {
  return apiFetch<void>(`/job-definition-store/${encodePath(name)}?archived=${archived ? "true" : "false"}`, {
    method: "DELETE",
  });
}

export async function archiveDefinition(name: string) {
  return apiFetch<void>(`/job-definition-store/${encodePath(name)}/archive`, { method: "POST" });
}

export async function restoreDefinition(name: string) {
  return apiFetch<DefinitionDocument>(`/job-definition-store/${encodePath(name)}/restore`, { method: "POST" });
}

// Package management
export async function listPackages() {
  return apiFetch<PackageList>("/packages");
}

export async function installPackage(spec: string, sourceType: PackageSourceType = "pypi") {
  // Package resolution/installation can take well over a minute; no timeout.
  return apiFetch<PackageOpResult>("/packages/install", {
    method: "POST",
    body: JSON.stringify({ spec, source_type: sourceType }),
  }, 0);
}

export async function uninstallPackage(name: string) {
  return apiFetch<PackageOpResult>("/packages/uninstall", {
    method: "POST",
    body: JSON.stringify({ name }),
  }, 0);
}

// Type library (Environment page)
export async function listTypeLibrary() {
  return apiFetch<{ types: TypeDef[] }>("/type-library");
}

export async function upsertType(name: string, body: { description?: string; fields: Record<string, unknown> }) {
  return apiFetch<TypeDef>(`/type-library/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function deleteType(name: string) {
  return apiFetch<void>(`/type-library/${encodeURIComponent(name)}`, { method: "DELETE" });
}

export async function extractType(qualifiedName: string) {
  return apiFetch<TypeExtractResponse>("/type-library/extract", {
    method: "POST",
    body: JSON.stringify({ qualified_name: qualifiedName }),
  });
}

// Saved typed values (per-researcher, reusable across published jobs)
export async function listSavedTypedValues() {
  return apiFetch<SavedTypedValue[]>("/saved-typed-values");
}

export async function saveTypedValue(payload: {
  type_key: string;
  container: "single" | "list" | "map";
  label?: string;
  type_schema: ResolvedType | Record<string, never>;
  value_kind?: "typed" | "plain";
  field_schema?: Partial<PublishedField>;
  value: unknown;
}) {
  return apiFetch<SavedTypedValue>("/saved-typed-values", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateSavedTypedValue(id: string, payload: { value?: unknown; label?: string }) {
  return apiFetch<SavedTypedValue>(`/saved-typed-values/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteSavedTypedValue(id: string) {
  return apiFetch<void>(`/saved-typed-values/${encodeURIComponent(id)}`, { method: "DELETE" });
}

// AI Designer
export async function getAIContext() {
  return apiFetch<AIContextResponse>("/ai-chat/context");
}

export async function testAIProvider(payload: AIProviderSelection) {
  return apiFetch<AIProviderTestResponse>("/ai-chat/test-provider", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// The AI chat endpoint streams: blank heartbeat lines keep the proxy connection
// alive during a long agent turn, then a single JSON line carries the result (or
// an `{ error }` payload, since the 200 status is already committed once
// streaming starts). We wait for the whole body and parse the last non-empty
// line. Heartbeats are not processed incrementally — they only exist to keep the
// connection from idling out.
export async function sendAIChatMessage(payload: AIChatRequest): Promise<AIChatResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), AI_CHAT_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}/ai-chat/messages`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
  } catch (cause) {
    if ((cause as { name?: string })?.name === "AbortError") {
      throw new Error(
        `AI request timed out after ${Math.round(AI_CHAT_TIMEOUT_MS / 1000)}s. Try a shorter request or fewer steps.`,
      );
    }
    throw cause;
  } finally {
    clearTimeout(timer);
  }

  // Pre-stream failures (notably auth) still arrive as a normal status + JSON.
  if (!response.ok) {
    if (response.status === 401) notifyUnauthorized();
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.detail ?? `API error ${response.status}`);
  }

  const text = await response.text();
  const lines = text.split("\n").map((line) => line.trim()).filter((line) => line.length > 0);
  const last = lines[lines.length - 1];
  if (!last) {
    throw new Error("AI chat returned an empty response. Wait a moment and retry.");
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(last);
  } catch {
    throw new Error("AI chat returned a malformed response. Wait a moment and retry.");
  }
  if (parsed && typeof parsed === "object" && "error" in parsed) {
    const err = (parsed as { error: { status?: number; detail?: string } }).error;
    if (err?.status === 401) notifyUnauthorized();
    throw new Error(err?.detail ?? "AI chat failed.");
  }
  return parsed as AIChatResponse;
}

export async function executeAITool(name: string, args: Record<string, unknown>, confirmed = false) {
  // A confirmed tool may submit and run jobs synchronously, so allow the longer
  // AI-chat budget rather than the default fail-fast timeout.
  return apiFetch<AIToolCallRecord>(
    "/ai-chat/tools/execute",
    {
      method: "POST",
      body: JSON.stringify({ name, arguments: args, confirmed }),
    },
    AI_CHAT_TIMEOUT_MS,
  );
}
