from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.schemas.pipelines import TemplateDocument, TemplateSummary
from bio_pipeline_manager.job_definition_templates import get_template, list_templates


router = APIRouter(prefix="/job-definition-templates", tags=["job-definition-templates"])


@router.get("", response_model=list[TemplateSummary])
async def list_job_definition_templates() -> list[TemplateSummary]:
    return [
        TemplateSummary(name=template.name, description=template.description)
        for template in list_templates()
    ]


@router.get("/{template_name}", response_model=TemplateDocument)
async def get_job_definition_template(template_name: str) -> TemplateDocument:
    try:
        template = get_template(template_name)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TemplateDocument(
        name=template.name,
        description=template.description,
        content=template.content,
    )
