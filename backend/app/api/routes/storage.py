from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime
from app.schemas.pipelines import YamlDocument, YamlSaveRequest, YamlSummary
from app.services.runtime import PipelineRuntime


router = APIRouter(prefix="/pipeline-yamls", tags=["pipeline-yamls"])


@router.get("", response_model=list[YamlSummary])
async def list_pipeline_yamls(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> list[YamlSummary]:
    return [
        YamlSummary(name=path.name, pipelines=runtime.yaml_store.pipeline_names(path.name))
        for path in runtime.yaml_store.list()
    ]


@router.post("", response_model=YamlDocument, status_code=status.HTTP_201_CREATED)
async def save_pipeline_yaml(
    body: YamlSaveRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> YamlDocument:
    try:
        path = runtime.yaml_store.save(body.name, body.content, overwrite=body.overwrite)
    except (FileExistsError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return YamlDocument(
        name=path.name,
        content=runtime.yaml_store.load(path.name),
        pipelines=runtime.yaml_store.pipeline_names(path.name),
    )


@router.get("/{yaml_name}", response_model=YamlDocument)
async def get_pipeline_yaml(
    yaml_name: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> YamlDocument:
    try:
        return YamlDocument(
            name=yaml_name,
            content=runtime.yaml_store.load(yaml_name),
            pipelines=runtime.yaml_store.pipeline_names(yaml_name),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
