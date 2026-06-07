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

export interface JobDefinitionTemplateSummary {
  name: string;
  description: string;
}

export interface JobDefinitionTemplate extends JobDefinitionTemplateSummary {
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
  parent_job_id?: string | null;
  job_name?: string;
  stage?: string;
  matrix_key?: Record<string, string>;
  created_at: string;
  updated_at: string;
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

export interface MaterializedTask {
  job_name: string;
  stage: string;
  matrix_key: Record<string, string>;
  needs: string[];
  pipeline_yaml: string;
  pipeline_name: string;
  output_dir: string;
  input_sources: Record<string, string>;
  process_arg_mapping: Record<string, Record<string, string>>;
  item_index: number;
  deferred?: boolean;
}

export interface JobDefinitionPreview {
  job_name: string;
  task_count: number;
  tasks: MaterializedTask[];
}

export interface JobGroupSummary {
  parent_job_id: string;
  job_name: string;
  status: string;
  total: number;
  counts: Record<string, number>;
}

export interface JobGroupDetail extends JobGroupSummary {
  tasks: Job[];
}

export interface PackageInfo {
  name: string;
  version: string;
}

export interface PackageOpResult {
  id: string;
  action: string;
  spec: string;
  source_type: string;
  resolved_version?: string | null;
  exit_code: number;
  ok: boolean;
  stdout: string;
  stderr: string;
  actor: string;
  created_at: string;
}

export interface PackageList {
  installed: PackageInfo[];
  history: PackageOpResult[];
}

export type PackageSourceType = "pypi" | "git" | "editable" | "requirements";

export type UserRole = "admin" | "user";

export interface User {
  id: string;
  username: string;
  display_name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  last_login_at?: string | null;
}

export interface AuthResponse {
  user: User;
}

export interface UserCreate {
  username: string;
  password: string;
  role: UserRole;
  display_name?: string;
  is_active?: boolean;
}

export interface UserUpdate {
  username?: string;
  display_name?: string;
  role?: UserRole;
  is_active?: boolean;
}

export interface DefinitionSummary {
  name: string;
  job: string;
  is_valid: boolean;
  error?: string | null;
}

export interface DefinitionTreeNode {
  name: string;
  path: string;
  node_type: "folder" | "file";
  job: string;
  is_valid: boolean;
  error?: string | null;
  children: DefinitionTreeNode[];
}

export interface DefinitionDocument {
  name: string;
  content: string;
  job: string;
  is_valid: boolean;
  error?: string | null;
}

export interface RuntimeInfo {
  pipeline_home: string;
  yaml_root: string;
  yaml_count: number;
  yaml_files: string[];
  cwd: string;
  env_pipeline_home?: string | null;
}
