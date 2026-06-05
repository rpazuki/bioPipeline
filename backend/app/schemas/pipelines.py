from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class YamlSummary(BaseModel):
    name: str
    pipelines: list[str]


class YamlDocument(BaseModel):
    name: str
    content: str
    pipelines: list[str]


class YamlSaveRequest(BaseModel):
    name: str
    content: str
    overwrite: bool = False


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


class JobSubmitRequest(BaseModel):
    yaml_name: str
    pipeline_name: str
    output_dir: str
    input_sources: dict[str, str] = Field(default_factory=dict)
    backend: str = "local"
    scheduled_at: datetime | None = None


class JobResponse(BaseModel):
    id: str
    status: str
    yaml_path: str
    pipeline_name: str
    output_dir: str
    input_sources: dict[str, str]
    backend: str
    log_path: str
    created_at: datetime
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    error: str | None = None


class JobLogResponse(BaseModel):
    id: str
    log: str

