import type {
  Job,
  JobSubmit,
  PipelineTemplate,
  PipelineTemplateSummary,
  ValidationReport,
  YamlDocument,
  YamlSummary,
} from "@/types";

const API_PREFIX = "/api/v1";

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
export async function listPipelineYamls() {
  return apiFetch<YamlSummary[]>("/pipeline-yamls");
}

export async function getPipelineYaml(name: string) {
  return apiFetch<YamlDocument>(`/pipeline-yamls/${encodeURIComponent(name)}`);
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
    `/validation/pipeline-yamls/${encodeURIComponent(name)}?imports=${imports ? "true" : "false"}`
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

