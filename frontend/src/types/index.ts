export interface YamlSummary {
  name: string;
  pipelines: string[];
}

export interface YamlDocument extends YamlSummary {
  content: string;
}

export interface ValidationIssue {
  level: "error" | "warning";
  message: string;
  pipeline?: string | null;
  section?: string | null;
  item?: string | null;
}

export interface ProcessSummary {
  name: string;
  package: string;
  method: string;
  parameters: Record<string, unknown>;
}

export interface PipelineSummary {
  name: string;
  inputs: string[];
  processes: ProcessSummary[];
  outputs: string[];
}

export interface ValidationReport {
  is_valid: boolean;
  issues: ValidationIssue[];
  pipelines: PipelineSummary[];
}

export interface PipelineTemplateSummary {
  name: string;
  description: string;
}

export interface PipelineTemplate extends PipelineTemplateSummary {
  content: string;
}

export interface Job {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  yaml_path: string;
  pipeline_name: string;
  output_dir: string;
  input_sources: Record<string, string>;
  backend: string;
  log_path: string;
  created_at: string;
  scheduled_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  exit_code?: number | null;
  error?: string | null;
}

export interface JobSubmit {
  yaml_name: string;
  pipeline_name: string;
  output_dir: string;
  input_sources: Record<string, string>;
  backend?: string;
  scheduled_at?: string | null;
}

