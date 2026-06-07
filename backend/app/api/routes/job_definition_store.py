from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_runtime
from app.schemas.pipelines import (
    DefinitionDocument,
    DefinitionSaveRequest,
    DefinitionSummary,
    DefinitionTreeNode,
    YamlFolderCreateRequest,
    YamlMoveRequest,
)
from app.services.runtime import PipelineRuntime


router = APIRouter(prefix="/job-definition-store", tags=["job-definition-store"])


@router.get("", response_model=list[DefinitionSummary])
async def list_definitions(runtime: Annotated[PipelineRuntime, Depends(get_runtime)]) -> list[DefinitionSummary]:
    store = runtime.definition_store
    return [_summary(store.relative_name(path), *store.summary(store.relative_name(path))) for path in store.list()]


@router.get("/tree", response_model=list[DefinitionTreeNode])
async def get_definition_tree(runtime: Annotated[PipelineRuntime, Depends(get_runtime)]) -> list[DefinitionTreeNode]:
    return _folder_children(runtime, runtime.definition_store.root)


@router.get("/archived", response_model=list[DefinitionSummary])
async def list_archived(runtime: Annotated[PipelineRuntime, Depends(get_runtime)]) -> list[DefinitionSummary]:
    store = runtime.definition_store
    summaries = []
    for path in store.list_archived():
        name = store.relative_archived_name(path)
        summaries.append(_summary(name, *store.summary(name, archived=True)))
    return summaries


@router.post("/folders", response_model=DefinitionTreeNode, status_code=status.HTTP_201_CREATED)
async def create_folder(
    body: YamlFolderCreateRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> DefinitionTreeNode:
    try:
        path = runtime.definition_store.create_folder(body.path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _folder_node(runtime, path)


@router.delete("/folders/{folder_path:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(folder_path: str, runtime: Annotated[PipelineRuntime, Depends(get_runtime)]) -> None:
    try:
        runtime.definition_store.delete_folder(folder_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("", response_model=DefinitionDocument, status_code=status.HTTP_201_CREATED)
async def save_definition(
    body: DefinitionSaveRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> DefinitionDocument:
    try:
        path = runtime.definition_store.save(body.name, body.content, overwrite=body.overwrite)
    except (FileExistsError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _document(runtime, runtime.definition_store.relative_name(path))


@router.post("/move", response_model=DefinitionDocument)
async def move_definition(
    body: YamlMoveRequest,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> DefinitionDocument:
    try:
        path = runtime.definition_store.move_file(body.source_path, body.destination_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (FileExistsError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _document(runtime, runtime.definition_store.relative_name(path))


@router.post("/{name:path}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive_definition(name: str, runtime: Annotated[PipelineRuntime, Depends(get_runtime)]) -> None:
    try:
        runtime.definition_store.archive(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{name:path}/restore", response_model=DefinitionDocument)
async def restore_definition(name: str, runtime: Annotated[PipelineRuntime, Depends(get_runtime)]) -> DefinitionDocument:
    try:
        runtime.definition_store.restore(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _document(runtime, name)


@router.delete("/{name:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_definition(
    name: str,
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
    archived: bool = False,
) -> None:
    try:
        runtime.definition_store.delete_file(name, archived=archived)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{name:path}", response_model=DefinitionDocument)
async def get_definition(name: str, runtime: Annotated[PipelineRuntime, Depends(get_runtime)]) -> DefinitionDocument:
    return _document(runtime, name)


def _summary(name: str, job: str, is_valid: bool, error: str | None) -> DefinitionSummary:
    return DefinitionSummary(name=name, job=job, is_valid=is_valid, error=error)


def _document(runtime: PipelineRuntime, name: str) -> DefinitionDocument:
    store = runtime.definition_store
    try:
        content = store.load(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    job, is_valid, error = store.summary(name)
    return DefinitionDocument(name=name, content=content, job=job, is_valid=is_valid, error=error)


def _folder_children(runtime: PipelineRuntime, folder) -> list[DefinitionTreeNode]:
    folder_path = folder if hasattr(folder, "iterdir") else runtime.definition_store.root
    children: list[DefinitionTreeNode] = []
    for path in sorted(folder_path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if path.is_dir():
            children.append(_folder_node(runtime, path))
        elif path.suffix in {".yaml", ".yml"}:
            children.append(_file_node(runtime, path))
    return children


def _folder_node(runtime: PipelineRuntime, path) -> DefinitionTreeNode:
    store = runtime.definition_store
    relative = "" if path.resolve() == store.root.resolve() else store.relative_name(path)
    return DefinitionTreeNode(
        name=path.name if relative else ".",
        path=relative,
        node_type="folder",
        children=_folder_children(runtime, path),
    )


def _file_node(runtime: PipelineRuntime, path) -> DefinitionTreeNode:
    store = runtime.definition_store
    name = store.relative_name(path)
    job, is_valid, error = store.summary(name)
    return DefinitionTreeNode(name=path.name, path=name, node_type="file", job=job, is_valid=is_valid, error=error)
