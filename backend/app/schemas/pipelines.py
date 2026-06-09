from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

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
    input_arg_mapping: dict[str, dict[str, Any]] = Field(default_factory=dict)
    process_arg_mapping: dict[str, dict[str, Any]] = Field(default_factory=dict)
    output_path_mapping: dict[str, Any] = Field(default_factory=dict)
    backend: str = "local"
    scheduled_at: datetime | None = None


class JobResponse(BaseModel):
    id: str
    status: str
    yaml_path: str
    pipeline_name: str
    output_dir: str
    input_sources: dict[str, str]
    input_arg_mapping: dict[str, dict[str, Any]] = Field(default_factory=dict)
    process_arg_mapping: dict[str, dict[str, Any]] = Field(default_factory=dict)
    output_path_mapping: dict[str, Any] = Field(default_factory=dict)
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
    input_arg_mapping: dict[str, dict[str, Any]] = Field(default_factory=dict)
    process_arg_mapping: dict[str, dict[str, Any]]
    output_path_mapping: dict[str, Any] = Field(default_factory=dict)
    item_index: int
    deferred: bool = False


class JobDefinitionRequest(BaseModel):
    content: str
    scheduled_at: datetime | None = None


class JobDefinitionPreviewResponse(BaseModel):
    job_name: str
    task_count: int
    tasks: list[MaterializedTaskResponse]
    warnings: list[str] = Field(default_factory=list)


class JobGroupSummary(BaseModel):
    parent_job_id: str
    job_name: str
    status: str
    total: int
    counts: dict[str, int]


class JobGroupDetail(JobGroupSummary):
    tasks: list[JobResponse]


class PublishedFieldOption(BaseModel):
    label: str
    value: Any


class PublishedFieldBinding(BaseModel):
    target: str
    path: list[Any] | None = None
    stage: str | None = None
    input: str | None = None
    process: str | None = None
    parameter: str | None = None
    output: str | None = None


class PublishedField(BaseModel):
    id: str
    label: str
    type: str = "string"
    required: bool = True
    readonly: bool = False
    default: Any = None
    help: str = ""
    example: str = ""
    placeholder: str = ""
    # Researcher-supplied I/O. ``io_role`` defaults to ``none`` so existing
    # fields keep their current (plain-value) behavior; an admin classifies a
    # path field as a researcher input or output at publish time.
    io_role: Literal["none", "input", "output"] = "none"
    accept: Literal["file", "directory"] = "file"
    sources: list[str] = Field(default_factory=list)
    delivery: list[str] = Field(default_factory=list)
    shared_roots: list[str] = Field(default_factory=list)
    options: list[PublishedFieldOption] = Field(default_factory=list)
    bindings: list[PublishedFieldBinding] = Field(default_factory=list)


class PublicPublishedField(BaseModel):
    id: str
    label: str
    type: str = "string"
    required: bool = True
    readonly: bool = False
    default: Any = None
    help: str = ""
    example: str = ""
    placeholder: str = ""
    io_role: Literal["none", "input", "output"] = "none"
    accept: Literal["file", "directory"] = "file"
    sources: list[str] = Field(default_factory=list)
    delivery: list[str] = Field(default_factory=list)
    shared_roots: list[str] = Field(default_factory=list)
    options: list[PublishedFieldOption] = Field(default_factory=list)


class PublishedJobInspectRequest(BaseModel):
    content: str


class PublishedJobInspectResponse(BaseModel):
    job_name: str
    candidates: list[PublishedField]
    warnings: list[str] = Field(default_factory=list)


class PublishedJobSaveRequest(BaseModel):
    name: str
    description: str = ""
    definition_name: str = ""
    definition_content: str
    fields: list[PublishedField]
    status: str = "draft"


class PublishedJobUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    definition_name: str | None = None
    definition_content: str | None = None
    fields: list[PublishedField] | None = None


class PublishedJobAdminResponse(BaseModel):
    id: str
    name: str
    description: str
    status: str
    version: int
    definition_name: str
    definition_content: str
    fields: list[PublishedField]
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    created_by: str
    updated_by: str


class PublishedJobPublicSummary(BaseModel):
    id: str
    name: str
    description: str
    version: int


class PublishedJobPublicDetail(PublishedJobPublicSummary):
    fields: list[PublicPublishedField]


class FileBinding(BaseModel):
    """How a researcher input field is satisfied at run time.

    ``upload`` → ``path`` is a workspace-relative handle from an upload;
    ``shared`` → ``path`` is a sub-path of allowlisted shared ``root`` (Phase 3).
    """

    kind: Literal["upload", "shared"] = "upload"
    path: str
    root: str | None = None


class DraftRunResponse(BaseModel):
    workspace_id: str


class SharedRootInfo(BaseModel):
    id: str
    label: str


class SharedEntryResponse(BaseModel):
    name: str
    path: str
    kind: Literal["file", "directory"]


class SharedBrowseResponse(BaseModel):
    root_id: str
    subpath: str
    entries: list[SharedEntryResponse]


class RunUploadResponse(BaseModel):
    field_id: str
    handle: str
    filename: str
    size: int


class PublishedJobRunRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    scheduled_at: datetime | None = None
    workspace_id: str | None = None
    file_bindings: dict[str, FileBinding] = Field(default_factory=dict)


class PublishedRunSummary(BaseModel):
    id: str
    published_job_id: str
    published_version: int
    published_job_name: str
    user_id: str
    username: str = ""
    user_display_name: str = ""
    parent_job_id: str
    status: str
    total: int
    counts: dict[str, int]
    values: dict[str, Any]
    workspace_id: str = ""
    artifact_available: bool = False
    created_at: datetime


class PublishedRunDetail(PublishedRunSummary):
    group: JobGroupDetail
    logs: dict[str, str] = Field(default_factory=dict)


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
