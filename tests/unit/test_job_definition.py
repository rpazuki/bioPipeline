from pathlib import Path

import pytest

from bio_pipeline_manager.job_definition import (
    JobDefinitionError,
    expand,
    iter_cells,
    parse_job_definition,
)


def _write_mapping(tmp_path: Path) -> Path:
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text(
        "mediabotJLF1.csv: protocol_a.csv\n"
        "mediabotJLF2.csv: protocol_b.csv\n",
        encoding="utf-8",
    )
    return mapping


def _growth_rates_def(mapping_path: Path) -> str:
    return f"""
job: growth_rates_full
description: Preprocess + collate across replicate variants
variables:
  run_tag: [TagA, TagB]
  variant:
    - {{name: no_replicates, pipeline: growth_rate_fit_pipeline}}
    - {{name: replicates, pipeline: growth_rate_replicates_fit_pipeline}}
defaults:
  data_root: "/data/{{run_tag}}"
stages:
  - name: preprocess
    pipeline_yaml: growth.yaml
    pipeline: "{{variant.pipeline}}"
    fanout:
      type: mapping_file
      mapping: "{mapping_path.as_posix()}"
      data_dir: "{{data_root}}/data"
    output_dir: "{{data_root}}/processed/{{variant.name}}/{{item.stem}}"
    input_sources:
      raw_data: "{{data_dir}}/{{item.raw}}"
      meta_data: "{{data_dir}}/{{item.meta}}"
  - name: collate
    needs: [preprocess]
    pipeline_yaml: collate.yaml
    pipeline: collate_per_strain_pipeline
    fanout: {{type: none}}
    input_sources:
      folders_list: "{{data_root}}/processed/{{variant.name}}"
    process_arg_mapping:
      saved_dataframes:
        strain_col: strain
        csv_input_file_name: growth_rates.csv
    output_dir: "{{data_root}}/processed/{{variant.name}}_STRAINS"
"""


def test_matrix_cartesian_product(tmp_path: Path):
    job_def = parse_job_definition(_growth_rates_def(_write_mapping(tmp_path)))
    cells = iter_cells(job_def)
    # 2 run_tags x 2 variants
    assert len(cells) == 4


def test_expand_counts_and_templating(tmp_path: Path):
    tasks = expand(_growth_rates_def(_write_mapping(tmp_path)))

    # 2 run_tags x 2 variants x (2 mapping pairs preprocess + 1 collate) = 12
    assert len(tasks) == 12
    preprocess = [t for t in tasks if t.stage == "preprocess"]
    collate = [t for t in tasks if t.stage == "collate"]
    assert len(preprocess) == 8
    assert len(collate) == 4

    # Pick a concrete preprocess task and verify full resolution.
    t = next(
        t
        for t in preprocess
        if t.matrix_key == {"run_tag": "TagA", "variant": "no_replicates"} and t.item_index == 0
    )
    assert t.pipeline_name == "growth_rate_fit_pipeline"
    assert t.output_dir == "/data/TagA/processed/no_replicates/mediabotJLF1"
    assert t.input_sources == {
        "raw_data": "/data/TagA/data/mediabotJLF1.csv",
        "meta_data": "/data/TagA/data/protocol_a.csv",
    }

    # Collate carries process_arg_mapping and depends on preprocess.
    c = next(c for c in collate if c.matrix_key == {"run_tag": "TagB", "variant": "replicates"})
    assert c.needs == ["preprocess"]
    assert c.output_dir == "/data/TagB/processed/replicates_STRAINS"
    assert c.input_sources == {"folders_list": "/data/TagB/processed/replicates"}
    assert c.process_arg_mapping == {
        "saved_dataframes": {"strain_col": "strain", "csv_input_file_name": "growth_rates.csv"}
    }


def test_folders_fanout(tmp_path: Path):
    root = tmp_path / "processed"
    (root / "expA").mkdir(parents=True)
    (root / "expB").mkdir(parents=True)
    text = f"""
job: collate_only
stages:
  - name: collate
    pipeline_yaml: c.yaml
    pipeline: collate
    fanout:
      type: folders
      data_dir: "{root.as_posix()}"
    output_dir: "{tmp_path.as_posix()}/out/{{item.name}}"
    input_sources:
      folder: "{{item.path}}"
"""
    tasks = expand(text)
    assert {t.input_sources["folder"] for t in tasks} == {str(root / "expA"), str(root / "expB")}
    assert {Path(t.output_dir).name for t in tasks} == {"expA", "expB"}


def test_no_variables_single_cell(tmp_path: Path):
    text = """
job: simple
stages:
  - name: only
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out
"""
    tasks = expand(text)
    assert len(tasks) == 1
    assert tasks[0].matrix_key == {}
    assert tasks[0].output_dir == "/out"


def test_unresolved_template_raises():
    text = """
job: bad
stages:
  - name: only
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: "/out/{missing_var}"
"""
    with pytest.raises(JobDefinitionError, match="unresolved template variable"):
        expand(text)


def test_unknown_needs_raises():
    text = """
job: bad
stages:
  - name: only
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out
    needs: [ghost]
"""
    with pytest.raises(JobDefinitionError, match="unknown stage 'ghost'"):
        parse_job_definition(text)


def test_dependency_cycle_raises():
    text = """
job: bad
stages:
  - name: a
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out
    needs: [b]
  - name: b
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out
    needs: [a]
"""
    with pytest.raises(JobDefinitionError, match="cycle"):
        parse_job_definition(text)


def test_missing_required_stage_key_raises():
    text = """
job: bad
stages:
  - name: only
    pipeline: demo
    fanout: {type: none}
    output_dir: /out
"""
    with pytest.raises(JobDefinitionError, match="missing required key 'pipeline_yaml'"):
        parse_job_definition(text)
