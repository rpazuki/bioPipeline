from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime
from app.schemas.pipelines import ValidateYamlRequest, ValidationReportResponse
from app.services.runtime import PipelineRuntime
from bio_pipeline_manager.yaml_validation import validate_labutils_yaml


router = APIRouter(prefix="/validation", tags=["validation"])


@router.post("/yaml", response_model=ValidationReportResponse)
async def validate_yaml_content(body: ValidateYamlRequest) -> ValidationReportResponse:
    return ValidationReportResponse(**validate_labutils_yaml(body.content, validate_imports=body.imports).as_dict())


@router.get("/pipeline-yamls/{yaml_name}", response_model=ValidationReportResponse)
async def validate_stored_yaml(
    yaml_name: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    imports: bool = False,
) -> ValidationReportResponse:
    try:
        report = runtime.yaml_store.validate(yaml_name, validate_imports=imports)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ValidationReportResponse(**report.as_dict())
