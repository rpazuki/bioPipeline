"""Starter Job Definition templates for common scenarios.

Mirrors :mod:`bio_pipeline_manager.templates` (pipeline templates) but for
**Job Definitions**. Each template is a valid, editable shell the web UI offers
on the Job Definitions page so users can pick a scenario and fill in the blanks
instead of writing a definition from scratch. All content parses with
:func:`bio_pipeline_manager.job_definition.parse_job_definition`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JobDefinitionTemplate:
    name: str
    description: str
    content: str


EMPTY = JobDefinitionTemplate(
    name="empty",
    description="Minimal one-stage shell. No matrix, no fan-out — fill in the blanks.",
    content="""job: new_job
description: ""

stages:
  - name: stage_one
    pipeline_yaml: my_pipeline.yaml
    pipeline: my_pipeline
    fanout: {type: none}
    output_dir: ./output
    input_sources:
      raw_data: ./data/input.csv
""",
)


SINGLE_STAGE = JobDefinitionTemplate(
    name="single_stage",
    description="One pipeline run with explicit inputs and a per-process parameter override.",
    content="""job: single_run
description: Run one pipeline once over a fixed input.

stages:
  - name: process
    pipeline_yaml: my_pipeline.yaml
    pipeline: my_pipeline
    fanout: {type: none}
    output_dir: ./output/result
    input_sources:
      raw_data: ./data/input.csv
    process_arg_mapping:
      my_process:
        column: value
""",
)


MATRIX_SWEEP = JobDefinitionTemplate(
    name="matrix_sweep",
    description="Sweep one pipeline across a matrix of variables (cartesian product of cells).",
    content="""job: parameter_sweep
description: One stage run once per matrix cell.

variables:
  batch: [batch-one, batch-two]
  variant:
    - {name: baseline, pipeline: baseline_pipeline}
    - {name: alternative, pipeline: alternative_pipeline}

defaults:
  data_root: "./data/{batch}"

stages:
  - name: analyse
    pipeline_yaml: my_pipeline.yaml
    pipeline: "{variant.pipeline}"
    fanout: {type: none}
    output_dir: "{data_root}/processed/{variant.name}"
    input_sources:
      raw_data: "{data_root}/input.csv"
""",
)


MAPPING_FANOUT = JobDefinitionTemplate(
    name="mapping_fanout",
    description="Fan out one Task per raw -> meta pair listed in a mapping file.",
    content="""job: per_file_run
description: One Task per data file, paired with its metadata via a mapping file.

defaults:
  # NOTE: data/sample/mapping.yaml is a DUMMY mapping shipped only so this page can
  # validate the fan-out as you edit. Point `mapping` and `data_dir` at your own
  # data folder before submitting a real run.
  data_root: ./data/sample

stages:
  - name: preprocess
    pipeline_yaml: my_pipeline.yaml
    pipeline: preprocess_pipeline
    fanout:
      type: mapping_file
      mapping: "{data_root}/mapping.yaml"   # read at preview/submit; replace with yours
      data_dir: "{data_root}/raw"           # not read here; only used for {data_dir}
    output_dir: "{data_root}/processed/{item.stem}"
    input_sources:
      raw_data: "{data_dir}/{item.raw}"
      meta_data: "{data_dir}/{item.meta}"
""",
)


PREPROCESS_COLLATE = JobDefinitionTemplate(
    name="preprocess_collate",
    description="Two-stage chain: preprocess, then a collate stage that waits for it.",
    content="""job: preprocess_then_collate
description: Preprocess inputs, then collate the results per cell.

defaults:
  # NOTE: data/sample/mapping.yaml is a DUMMY mapping shipped only so this page can
  # validate the fan-out as you edit. Point `mapping` and `data_dir` at your own
  # data folder before submitting a real run.
  data_root: ./data/sample

stages:
  - name: preprocess
    pipeline_yaml: preprocess_pipeline.yaml
    pipeline: preprocess_pipeline
    fanout:
      type: mapping_file
      mapping: "{data_root}/mapping.yaml"   # read at preview/submit; replace with yours
      data_dir: "{data_root}/raw"           # not read here; only used for {data_dir}
    output_dir: "{data_root}/processed/{item.stem}"
    input_sources:
      raw_data: "{data_dir}/{item.raw}"
      meta_data: "{data_dir}/{item.meta}"

  - name: collate
    needs: [preprocess]                      # waits for preprocess; fans out at run time
    pipeline_yaml: collate_pipeline.yaml
    pipeline: collate_pipeline
    fanout: {type: none}
    input_sources:
      folders_list: "{data_root}/processed"
    process_arg_mapping:
      saved_dataframes:
        group_col: group
        csv_input_file_name: results.csv
    output_dir: "{data_root}/collated"
""",
)


FOLDERS_FANOUT = JobDefinitionTemplate(
    name="folders_fanout",
    description="Fan out one Task per sub-folder of a directory (collate everything under it).",
    content="""job: per_folder_run
description: One Task per immediate sub-folder of a directory.

defaults:
  # NOTE: data/sample/processed holds DUMMY sub-folders shipped only so this page
  # can validate the fan-out as you edit. Point `data_dir` at your own data folder
  # before submitting a real run.
  data_root: ./data/sample/processed

stages:
  - name: summarise
    pipeline_yaml: my_pipeline.yaml
    pipeline: summarise_pipeline
    fanout:
      type: folders
      data_dir: "{data_root}"   # listed at preview/submit; replace with yours
    output_dir: "{data_root}/{item.name}_summary"
    input_sources:
      folder: "{item.path}"
""",
)


TEMPLATES = {
    template.name: template
    for template in (
        EMPTY,
        SINGLE_STAGE,
        MATRIX_SWEEP,
        MAPPING_FANOUT,
        PREPROCESS_COLLATE,
        FOLDERS_FANOUT,
    )
}


def list_templates() -> list[JobDefinitionTemplate]:
    return sorted(TEMPLATES.values(), key=lambda template: template.name)


def get_template(name: str) -> JobDefinitionTemplate:
    try:
        return TEMPLATES[name]
    except KeyError as exc:
        raise KeyError(f"Unknown job definition template: {name}") from exc
