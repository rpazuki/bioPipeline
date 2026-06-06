"""Project-native pipeline engine and reusable process functions.

The ``pipeline`` package owns pipeline orchestration (the process/YAML engine,
transferred from the external ``labUtils`` package). Science process functions
remain in ``labUtils`` and are referenced from YAML as ``package: labUtils.*``.
"""

from pipeline.engine import (
    DFPipeline,
    Dict,
    IncompatibleArgsException,
    build_pipeline_from_yaml,
    build_pipeline_from_yaml_string,
)
from pipeline.io import (
    create_file_mapping_from_patterns,
    list_folders,
    load_file_mapping,
    read_csv,
)

__all__ = [
    "DFPipeline",
    "Dict",
    "IncompatibleArgsException",
    "build_pipeline_from_yaml",
    "build_pipeline_from_yaml_string",
    "create_file_mapping_from_patterns",
    "list_folders",
    "load_file_mapping",
    "read_csv",
]
