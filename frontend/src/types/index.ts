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
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "blocked";
  yaml_path: string;
  pipeline_name: string;
  output_dir: string;
  input_sources: Record<string, string>;
  input_arg_mapping?: Record<string, Record<string, unknown>>;
  process_arg_mapping?: Record<string, Record<string, unknown>>;
  output_path_mapping?: Record<string, unknown>;
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
  input_arg_mapping?: Record<string, Record<string, unknown>>;
  process_arg_mapping?: Record<string, Record<string, unknown>>;
  output_path_mapping?: Record<string, unknown>;
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
  input_arg_mapping?: Record<string, Record<string, unknown>>;
  process_arg_mapping: Record<string, Record<string, unknown>>;
  output_path_mapping?: Record<string, unknown>;
  item_index: number;
  deferred?: boolean;
}

export interface JobDefinitionPreview {
  job_name: string;
  task_count: number;
  tasks: MaterializedTask[];
  warnings: string[];
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

export type PublishedFieldType =
  | "string"
  | "text"
  | "integer"
  | "float"
  | "boolean"
  | "enum"
  | "multi_enum"
  | "path"
  | "file"
  | "directory"
  | "glob"
  | "datetime"
  | "list"
  | "object"
  | "json";

export interface PublishedFieldOption {
  label: string;
  value: unknown;
}

export interface SharedRootInfo {
  id: string;
  label: string;
}

export interface SharedEntry {
  name: string;
  path: string;
  kind: "file" | "directory";
}

export interface PublishedFieldBinding {
  target: string;
  path?: unknown[] | null;
  stage?: string | null;
  input?: string | null;
  process?: string | null;
  parameter?: string | null;
  output?: string | null;
}

export type PublishedFieldIoRole = "none" | "input" | "output";

export interface PublishedField {
  id: string;
  label: string;
  type: PublishedFieldType;
  required: boolean;
  readonly?: boolean;
  default?: unknown;
  help: string;
  example: string;
  placeholder?: string;
  io_role?: PublishedFieldIoRole;
  accept?: "file" | "directory";
  sources?: string[];
  delivery?: string[];
  shared_roots?: string[];
  options: PublishedFieldOption[];
  bindings?: PublishedFieldBinding[];
}

export interface PublishedJobAdmin {
  id: string;
  name: string;
  description: string;
  status: "draft" | "published" | "archived";
  version: number;
  definition_name: string;
  definition_content: string;
  fields: PublishedField[];
  created_at: string;
  updated_at: string;
  published_at?: string | null;
  created_by: string;
  updated_by: string;
}

export interface PublishedJobPublicSummary {
  id: string;
  name: string;
  description: string;
  version: number;
}

export interface PublishedJobPublicDetail extends PublishedJobPublicSummary {
  fields: PublishedField[];
}

export interface PublishedRunSummary {
  id: string;
  published_job_id: string;
  published_version: number;
  published_job_name: string;
  user_id: string;
  username: string;
  user_display_name: string;
  parent_job_id: string;
  status: string;
  total: number;
  counts: Record<string, number>;
  values: Record<string, unknown>;
  workspace_id?: string;
  artifact_available?: boolean;
  created_at: string;
}

export interface PublishedRunDetail extends PublishedRunSummary {
  group: JobGroupDetail;
  logs: Record<string, string>;
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
  description: string;
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

// AI Designer
export type AIProvider = "claude" | "openai" | "gemini" | "openai_compatible" | "fake";

export interface AIProviderStatus {
  provider: string;
  enabled: boolean;
  configured: boolean;
  model: string;
  base_url: string;
  is_default: boolean;
}

export interface AIProviderSelection {
  provider?: AIProvider | null;
  model?: string | null;
  temperature?: number | null;
  max_tokens?: number | null;
}

export interface AIProviderTestResponse {
  ok: boolean;
  provider: string;
  model: string;
  message: string;
}

export interface AIToolDefinition {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  read_only: boolean;
  requires_confirmation: boolean;
}

export interface AIContextResponse {
  context: string;
  default_provider: string;
  providers: AIProviderStatus[];
  max_tool_iterations: number;
  schema_digest: string;
  tools: AIToolDefinition[];
}

export interface AIChatMessage {
  role: "user" | "assistant";
  content: string;
}

export type AIToolCallStatus =
  | "pending_confirmation"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped";

export interface AIToolCallRecord {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  status: AIToolCallStatus;
  result?: Record<string, unknown> | null;
  error?: string | null;
  requires_confirmation: boolean;
}

export interface AIArtifactDraft {
  kind: "pipeline_yaml" | "job_definition";
  name: string;
  content: string | Record<string, unknown> | unknown[];
  source: "model" | "tool";
}

export interface AIChatRequest {
  provider?: AIProviderSelection;
  messages: AIChatMessage[];
  active_pipeline_yaml?: string;
  active_job_definition?: string;
  confirmations?: Record<string, boolean>;
}

export interface AIChatResponse {
  message: AIChatMessage;
  tool_calls: AIToolCallRecord[];
  drafts: AIArtifactDraft[];
  needs_confirmation?: AIToolCallRecord | null;
}
