from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class YamlSummary(BaseModel):
    name: str
    pipelines: list[str]
    is_valid: bool = True
    error: str | None = None


class YamlTreeNode(BaseModel):
    name: str
    path: str
    node_type: str
    pipelines: list[str] = Field(default_factory=list)
    is_valid: bool = True
    error: str | None = None
    children: list["YamlTreeNode"] = Field(default_factory=list)


class YamlDocument(BaseModel):
    name: str
    content: str
    pipelines: list[str]
    is_valid: bool = True
    error: str | None = None


class YamlSaveRequest(BaseModel):
    name: str
    content: str
    overwrite: bool = False


class YamlFolderCreateRequest(BaseModel):
    path: str


class YamlMoveRequest(BaseModel):
    source_path: str
    destination_path: str


class ValidationIssueResponse(BaseModel):
    level: str
    message: str
    pipeline: str | None = None
    section: str | None = None
    item: str | None = None


class ProcessSummaryResponse(BaseModel):
    name: str
    package: str
    method: str
    parameters: dict


class PipelineSummaryResponse(BaseModel):
    name: str
    inputs: list[str]
    processes: list[ProcessSummaryResponse]
    outputs: list[str]


class ValidationReportResponse(BaseModel):
    is_valid: bool
    issues: list[ValidationIssueResponse]
    pipelines: list[PipelineSummaryResponse]


class ValidateYamlRequest(BaseModel):
    content: str
    imports: bool = False


class TemplateSummary(BaseModel):
    name: str
    description: str


class TemplateDocument(TemplateSummary):
    content: str


class RuntimeInfo(BaseModel):
    pipeline_home: str
    yaml_root: str
    yaml_count: int
    yaml_files: list[str]
    cwd: str
    env_pipeline_home: str | None = None


class JobSubmitRequest(BaseModel):
    yaml_name: str
    pipeline_name: str
    output_dir: str
    input_sources: dict[str, str] = Field(default_factory=dict)
    process_arg_mapping: dict[str, dict[str, str]] = Field(default_factory=dict)
    backend: str = "local"
    scheduled_at: datetime | None = None


class JobResponse(BaseModel):
    id: str
    status: str
    yaml_path: str
    pipeline_name: str
    output_dir: str
    input_sources: dict[str, str]
    process_arg_mapping: dict[str, dict[str, str]] = Field(default_factory=dict)
    backend: str
    log_path: str
    parent_job_id: str | None = None
    job_name: str = ""
    stage: str = ""
    matrix_key: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    error: str | None = None
    pid: int | None = None


class JobLogResponse(BaseModel):
    id: str
    log: str


class MaterializedTaskResponse(BaseModel):
    job_name: str
    stage: str
    matrix_key: dict[str, str]
    needs: list[str]
    pipeline_yaml: str
    pipeline_name: str
    output_dir: str
    input_sources: dict[str, str]
    process_arg_mapping: dict[str, dict[str, str]]
    item_index: int
    deferred: bool = False


class JobDefinitionRequest(BaseModel):
    content: str
    scheduled_at: datetime | None = None


class JobDefinitionPreviewResponse(BaseModel):
    job_name: str
    task_count: int
    tasks: list[MaterializedTaskResponse]


class JobGroupSummary(BaseModel):
    parent_job_id: str
    job_name: str
    status: str
    total: int
    counts: dict[str, int]


class JobGroupDetail(JobGroupSummary):
    tasks: list[JobResponse]


class PackageInfo(BaseModel):
    name: str
    version: str


class PackageOpResultResponse(BaseModel):
    id: str
    action: str
    spec: str
    source_type: str
    resolved_version: str | None = None
    exit_code: int
    ok: bool
    stdout: str
    stderr: str
    actor: str
    created_at: str


class PackageListResponse(BaseModel):
    installed: list[PackageInfo]
    history: list[PackageOpResultResponse]


class InstallRequest(BaseModel):
    spec: str
    source_type: str = "pypi"


class UninstallRequest(BaseModel):
    name: str


class DefinitionSummary(BaseModel):
    name: str
    job: str = ""
    is_valid: bool = True
    error: str | None = None


class DefinitionTreeNode(BaseModel):
    name: str
    path: str
    node_type: str
    job: str = ""
    is_valid: bool = True
    error: str | None = None
    children: list["DefinitionTreeNode"] = Field(default_factory=list)


class DefinitionDocument(BaseModel):
    name: str
    content: str
    job: str = ""
    is_valid: bool = True
    error: str | None = None


class DefinitionSaveRequest(BaseModel):
    name: str
    content: str
    overwrite: bool = False


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str = ""
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None


class AuthResponse(BaseModel):
    user: UserResponse


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "user"
    display_name: str = ""
    is_active: bool = True


class UserUpdateRequest(BaseModel):
    username: str | None = None
    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None


class PasswordResetRequest(BaseModel):
    password: str
