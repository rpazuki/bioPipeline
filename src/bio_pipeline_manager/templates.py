from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineTemplate:
    name: str
    description: str
    content: str


MINIMAL_PIPELINE = PipelineTemplate(
    name="minimal",
    description="Small labUtils-compatible pipeline with one input, one process, and one output.",
    content="""pipelines:
  - example_pipeline:
      Inputs:
        - raw_data:
            - src: ./data/input.csv
            - package: pandas
            - method: read_csv
      Processes:
        - df_processed:
            package: labUtils.utils
            method: smart_join_drop_right
            parameters:
              left_df: raw_data
              right_df: raw_data
              on_cols:
                - id
      Outputs:
        - df_processed: processed.csv
""",
)


EMPTY_PIPELINE = PipelineTemplate(
    name="empty",
    description="Editable shell for starting a new labUtils pipeline.",
    content="""pipelines:
  - new_pipeline:
      Inputs: []
      Processes: []
      Outputs: []
""",
)


TEMPLATES = {
    template.name: template
    for template in (
        EMPTY_PIPELINE,
        MINIMAL_PIPELINE,
    )
}


def list_templates() -> list[PipelineTemplate]:
    return sorted(TEMPLATES.values(), key=lambda template: template.name)


def get_template(name: str) -> PipelineTemplate:
    try:
        return TEMPLATES[name]
    except KeyError as exc:
        raise KeyError(f"Unknown template: {name}") from exc

