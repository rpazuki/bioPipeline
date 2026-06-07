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
  RuntimeInfo,
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

function encodePath(path: string) {
  return path
    .split("/")
    .filter((part) => part.length > 0)
    .map((part) => encodeURIComponent(part))
    .join("/");
}

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  const response = await fetch(`${API_PREFIX}${path}`, { credentials: "include", ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (body?.detail) {
      throw new Error(body.detail);
    }
    // No JSON detail on a 5xx usually means the dev proxy returned it (backend
    // restarted or the request timed out), not the API itself.
    if (response.status >= 500) {
      throw new Error(
        `Server error ${response.status} — the backend may have restarted or the request timed out. Wait a moment and retry.`,
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

export async function runDueJobs(parallel = 1) {
  return apiFetch<Job[]>(`/jobs/run-due?parallel=${parallel}`, {
    method: "POST",
  });
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

export async function rewindJob(jobId: string) {
  return apiFetch<Job>(`/jobs/${jobId}/rewind`, {
    method: "POST",
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
  return apiFetch<{ job_name: string; candidates: PublishedField[] }>("/published-jobs/admin/inspect", {
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
  return apiFetch<{ is_valid: boolean; candidate_count: number; field_count: number; run_count: number }>(
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

export async function submitPublishedJobRun(id: string, values: Record<string, unknown>, scheduledAt: string | null = null) {
  return apiFetch<PublishedRunDetail>(`/published-jobs/catalog/${encodeURIComponent(id)}/runs`, {
    method: "POST",
    body: JSON.stringify({ values, scheduled_at: scheduledAt }),
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

export async function rewindMyPublishedRun(id: string) {
  return apiFetch<PublishedRunDetail>(`/published-jobs/my-runs/${encodeURIComponent(id)}/rewind`, { method: "POST" });
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
  return apiFetch<PackageOpResult>("/packages/install", {
    method: "POST",
    body: JSON.stringify({ spec, source_type: sourceType }),
  });
}

export async function uninstallPackage(name: string) {
  return apiFetch<PackageOpResult>("/packages/uninstall", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
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

export async function sendAIChatMessage(payload: AIChatRequest) {
  return apiFetch<AIChatResponse>("/ai-chat/messages", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function executeAITool(name: string, args: Record<string, unknown>, confirmed = false) {
  return apiFetch<AIToolCallRecord>("/ai-chat/tools/execute", {
    method: "POST",
    body: JSON.stringify({ name, arguments: args, confirmed }),
  });
}
