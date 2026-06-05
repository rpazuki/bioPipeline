from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.services.runtime import PipelineRuntime, create_runtime


@lru_cache
def get_runtime() -> PipelineRuntime:
    return create_runtime(settings.pipeline_home)

