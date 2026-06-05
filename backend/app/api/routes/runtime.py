from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_runtime
from app.schemas.pipelines import RuntimeInfo
from app.services.runtime import PipelineRuntime


router = APIRouter(prefix="/runtime", tags=["runtime"])


@router.get("", response_model=RuntimeInfo)
async def runtime_info(
    runtime: Annotated[PipelineRuntime, Depends(get_runtime)],
) -> RuntimeInfo:
    yaml_root = runtime.yaml_store.root
    yaml_files = [path.name for path in runtime.yaml_store.list()]
    return RuntimeInfo(
        pipeline_home=str(runtime.home),
        yaml_root=str(yaml_root),
        yaml_count=len(yaml_files),
        yaml_files=yaml_files,
        cwd=str(Path.cwd()),
        env_pipeline_home=os.environ.get("PIPELINE_HOME"),
    )
