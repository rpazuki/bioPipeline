import type {
  Job,
  JobSubmit,
  PipelineTemplate,
  PipelineTemplateSummary,
  RuntimeInfo,
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
  const response = await fetch(`${API_PREFIX}${path}`, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.detail ?? `API error ${response.status}`);
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

export async function getJobLogs(jobId: string) {
  return apiFetch<{ id: string; log: string }>(`/jobs/${jobId}/logs`);
}
