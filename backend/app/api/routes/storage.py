from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime
from app.schemas.pipelines import YamlDocument, YamlFolderCreateRequest, YamlMoveRequest, YamlSaveRequest, YamlSummary, YamlTreeNode
from app.services.runtime import PipelineRuntime


router = APIRouter(prefix="/pipeline-yamls", tags=["pipeline-yamls"])


@router.get("", response_model=list[YamlSummary])
async def list_pipeline_yamls(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> list[YamlSummary]:
    summaries: list[YamlSummary] = []
    for path in runtime.yaml_store.list():
        name = runtime.yaml_store.relative_name(path)
        try:
            summaries.append(
                YamlSummary(name=name, pipelines=runtime.yaml_store.pipeline_names(name))
            )
        except ValueError as exc:
            summaries.append(
                YamlSummary(name=name, pipelines=[], is_valid=False, error=str(exc))
            )
    return summaries


@router.get("/tree", response_model=list[YamlTreeNode])
async def get_pipeline_yaml_tree(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> list[YamlTreeNode]:
    return _folder_children(runtime, runtime.yaml_store.root)


@router.post("/folders", response_model=YamlTreeNode, status_code=status.HTTP_201_CREATED)
async def create_pipeline_yaml_folder(
    body: YamlFolderCreateRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> YamlTreeNode:
    try:
        path = runtime.yaml_store.create_folder(body.path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _folder_node(runtime, path)


@router.delete("/folders/{folder_path:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline_yaml_folder(
    folder_path: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> None:
    try:
        runtime.yaml_store.delete_folder(folder_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("", response_model=YamlDocument, status_code=status.HTTP_201_CREATED)
async def save_pipeline_yaml(
    body: YamlSaveRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> YamlDocument:
    try:
        path = runtime.yaml_store.save(body.name, body.content, overwrite=body.overwrite)
    except (FileExistsError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _yaml_document(runtime, runtime.yaml_store.relative_name(path))


@router.post("/move", response_model=YamlDocument)
async def move_pipeline_yaml(
    body: YamlMoveRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> YamlDocument:
    try:
        path = runtime.yaml_store.move_file(body.source_path, body.destination_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (FileExistsError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _yaml_document(runtime, runtime.yaml_store.relative_name(path))


@router.delete("/{yaml_name:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline_yaml(
    yaml_name: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> None:
    try:
        runtime.yaml_store.delete_file(yaml_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{yaml_name:path}", response_model=YamlDocument)
async def get_pipeline_yaml(
    yaml_name: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> YamlDocument:
    return _yaml_document(runtime, yaml_name)


def _yaml_document(
    runtime: PipelineRuntime,
    yaml_name: str,
) -> YamlDocument:
    try:
        content = runtime.yaml_store.load(yaml_name)
        try:
            pipelines = runtime.yaml_store.pipeline_names(yaml_name)
            return YamlDocument(name=yaml_name, content=content, pipelines=pipelines)
        except ValueError as exc:
            return YamlDocument(name=yaml_name, content=content, pipelines=[], is_valid=False, error=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _folder_children(runtime: PipelineRuntime, folder: str | object) -> list[YamlTreeNode]:
    folder_path = folder if hasattr(folder, "iterdir") else runtime.yaml_store.resolve_folder(str(folder))
    children: list[YamlTreeNode] = []
    for path in sorted(folder_path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if path.is_dir():
            children.append(_folder_node(runtime, path))
        elif path.suffix in {".yaml", ".yml"}:
            children.append(_file_node(runtime, path))
    return children


def _folder_node(runtime: PipelineRuntime, path) -> YamlTreeNode:
    relative = "" if path.resolve() == runtime.yaml_store.root.resolve() else runtime.yaml_store.relative_name(path)
    return YamlTreeNode(
        name=path.name if relative else ".",
        path=relative,
        node_type="folder",
        children=_folder_children(runtime, path),
    )


def _file_node(runtime: PipelineRuntime, path) -> YamlTreeNode:
    name = runtime.yaml_store.relative_name(path)
    try:
        return YamlTreeNode(
            name=path.name,
            path=name,
            node_type="file",
            pipelines=runtime.yaml_store.pipeline_names(name),
        )
    except ValueError as exc:
        return YamlTreeNode(
            name=path.name,
            path=name,
            node_type="file",
            pipelines=[],
            is_valid=False,
            error=str(exc),
        )
