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
    saveable: bool = False
    # When true, an empty researcher entry is submitted as Python None (YAML null)
    # instead of an empty string, so the scientific function receives None.
    nullable: bool = False
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
    # Structured-type binding (type == "typed"): the library type name, the container
    # shape, and the resolved self-contained schema tree. ``schema_suggestion*`` are
    # set only on inspect candidates as a non-binding hint.
    schema_ref: str = ""
    container: Literal["single", "list", "map"] = "single"
    type_schema: dict[str, Any] | None = None
    schema_suggestion: str = ""
    schema_suggestion_container: str = ""


class PublicPublishedField(BaseModel):
    id: str
    label: str
    type: str = "string"
    required: bool = True
    readonly: bool = False
    saveable: bool = False
    nullable: bool = False
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
    # Researchers need the structured-type info to render the typed editor; the
    # binding (``bindings``) stays admin-only.
    schema_ref: str = ""
    container: Literal["single", "list", "map"] = "single"
    type_schema: dict[str, Any] | None = None


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


class PublishedRunRewindRequest(BaseModel):
    """Re-run an existing run now, or (schedule-again) at a chosen time."""

    scheduled_at: datetime | None = None


class RecurringScheduleCreateRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    file_bindings: dict[str, FileBinding] = Field(default_factory=dict)
    workspace_id: str | None = None
    every_n: int = 1
    unit: Literal["minutes", "hours", "days", "weeks"] = "days"
    ends_mode: Literal["never", "count", "until"] = "never"
    ends_count: int = 0
    ends_at: datetime | None = None
    # First occurrence; defaults to "as soon as the scheduler next ticks".
    start_at: datetime | None = None


class RecurringScheduleResponse(BaseModel):
    id: str
    published_job_id: str
    published_job_name: str = ""
    published_version: int
    every_n: int
    unit: str
    ends_mode: str
    ends_count: int
    ends_at: datetime | None = None
    next_run_at: datetime
    runs_done: int
    active: bool
    created_at: datetime
    last_run_at: datetime | None = None
    values: dict[str, Any] = Field(default_factory=dict)


class RecurringJobCreateRequest(BaseModel):
    """Submit a plain job repeatedly on a fixed interval (admin side)."""

    job: JobSubmitRequest
    every_n: int = 1
    unit: Literal["minutes", "hours", "days", "weeks"] = "days"
    ends_mode: Literal["never", "count", "until"] = "never"
    ends_count: int = 0
    ends_at: datetime | None = None
    start_at: datetime | None = None


class RecurringJobResponse(BaseModel):
    id: str
    name: str
    every_n: int
    unit: str
    ends_mode: str
    ends_count: int
    ends_at: datetime | None = None
    next_run_at: datetime
    runs_done: int
    active: bool
    created_at: datetime
    last_run_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


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
    description: str = ""
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


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class TypeDefRequest(BaseModel):
    # Fields are passed through as raw specs; the store's validate_library enforces
    # structure (known refs, valid containers, enums carry options, no cycles).
    description: str = ""
    fields: dict[str, dict[str, Any]]


class TypeDefResponse(BaseModel):
    name: str
    description: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)


class TypeLibraryResponse(BaseModel):
    types: list[TypeDefResponse] = Field(default_factory=list)


class TypeExtractRequest(BaseModel):
    qualified_name: str


class TypeExtractResponse(BaseModel):
    # Raw library entries (name -> {description, fields}) ready to upsert, the root
    # type's name, and any best-effort fallbacks the introspection had to make.
    types: dict[str, Any] = Field(default_factory=dict)
    root: str = ""
    warnings: list[str] = Field(default_factory=list)


# --- Saved typed values (per-researcher reusable structured field values) ---- #
class SavedTypedValueResponse(BaseModel):
    id: str
    type_key: str
    container: Literal["single", "list", "map"] = "single"
    label: str = ""
    type_schema: dict[str, Any] = Field(default_factory=dict)
    value_kind: Literal["typed", "plain"] = "typed"
    field_schema: dict[str, Any] = Field(default_factory=dict)
    value: Any = None
    created_at: datetime
    updated_at: datetime


class SavedTypedValueUpsertRequest(BaseModel):
    """Save (create or replace) a researcher's value for a type + container.

    Keyed server-side by the authenticated user plus ``type_key``/``container``,
    so re-saving the same type overwrites the previous value.
    """

    type_key: str
    container: Literal["single", "list", "map"] = "single"
    label: str = ""
    type_schema: dict[str, Any] = Field(default_factory=dict)
    value_kind: Literal["typed", "plain"] = "typed"
    field_schema: dict[str, Any] = Field(default_factory=dict)
    value: Any = None


class SavedTypedValueUpdateRequest(BaseModel):
    value: Any = None
    label: str | None = None
