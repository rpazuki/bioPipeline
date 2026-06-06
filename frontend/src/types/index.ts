export interface YamlSummary {
  name: string;
  pipelines: string[];
  is_valid: boolean;
  error?: string | null;
}

export interface YamlTreeNode {
  name: string;
  path: string;
  node_type: "folder" | "file";
  pipelines: string[];
  is_valid: boolean;
  error?: string | null;
  children: YamlTreeNode[];
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
  process_arg_mapping?: Record<string, Record<string, string>>;
  backend: string;
  log_path: string;
  created_at: string;
  scheduled_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  exit_code?: number | null;
  error?: string | null;
  pid?: number | null;
}

export interface JobSubmit {
  yaml_name: string;
  pipeline_name: string;
  output_dir: string;
  input_sources: Record<string, string>;
  process_arg_mapping?: Record<string, Record<string, string>>;
  backend?: string;
  scheduled_at?: string | null;
}

export interface RuntimeInfo {
  pipeline_home: string;
  yaml_root: string;
  yaml_count: number;
  yaml_files: string[];
  cwd: string;
  env_pipeline_home?: string | null;
}
