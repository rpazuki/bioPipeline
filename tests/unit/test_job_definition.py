from pathlib import Path

import pytest

from bio_pipeline_manager.job_definition import (
    JobDefinitionError,
    expand,
    fanout_warnings,
    iter_cells,
    parse_job_definition,
)


_FANOUT_NO_ITEM = """
job: multi
defaults:
  data_root: /data
  mapping_yaml: /data/mapping.yaml
stages:
  - name: fit
    pipeline_yaml: p.yaml
    pipeline: fit
    fanout:
      type: mapping_file
      mapping: "{mapping_yaml}"
    input_sources:
      raw_data: "{data_root}"
      meta_data: "{data_root}"
    output_dir: /out
"""


def test_fanout_warning_when_no_item_token():
    # mapping_file fan-out whose inputs/outputs never reference {item.*} would
    # produce N identical tasks — must be flagged.
    warnings = fanout_warnings(parse_job_definition(_FANOUT_NO_ITEM))
    assert len(warnings) == 1
    assert "fit" in warnings[0]
    assert "item" in warnings[0]


def test_no_warning_when_item_token_present():
    text = _FANOUT_NO_ITEM.replace('raw_data: "{data_root}"', 'raw_data: "{data_root}/{item.raw}"')
    assert fanout_warnings(parse_job_definition(text)) == []


def test_no_warning_when_item_only_in_output_dir():
    text = _FANOUT_NO_ITEM.replace("output_dir: /out", "output_dir: /out/{item.stem}")
    assert fanout_warnings(parse_job_definition(text)) == []


def test_no_warning_for_fanout_none():
    text = _FANOUT_NO_ITEM.replace("type: mapping_file", "type: none")
    assert fanout_warnings(parse_job_definition(text)) == []


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


def test_patterns_fanout(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    for name in ["raw1.csv", "raw2.csv", "meta1.csv", "meta2.csv"]:
        (data / name).write_text("x", encoding="utf-8")
    text = f"""
job: pat
stages:
  - name: prep
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout:
      type: patterns
      data_dir: "{data.as_posix()}"
      raw_pattern: "raw*.csv"
      meta_pattern: "meta*.csv"
    output_dir: "/out/{{item.stem}}"
    input_sources:
      raw: "{{data_dir}}/{{item.raw}}"
      meta: "{{data_dir}}/{{item.meta}}"
"""
    tasks = expand(text)
    assert len(tasks) == 2
    stems = {t.output_dir for t in tasks}
    assert stems == {"/out/raw1", "/out/raw2"}
    t = next(t for t in tasks if t.output_dir == "/out/raw1")
    assert t.input_sources == {"raw": f"{data.as_posix()}/raw1.csv", "meta": f"{data.as_posix()}/meta1.csv"}


def test_mapping_file_csv(tmp_path: Path):
    mapping = tmp_path / "m.csv"
    mapping.write_text("raw,meta\nr1.csv,m1.csv\nr2.csv,m2.csv\n", encoding="utf-8")
    text = f"""
job: m
stages:
  - name: prep
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {{type: mapping_file, mapping: "{mapping.as_posix()}"}}
    output_dir: "/out/{{item.stem}}"
    input_sources: {{raw: "{{item.raw}}", meta: "{{item.meta}}"}}
"""
    tasks = expand(text)
    assert {t.input_sources["raw"] for t in tasks} == {"r1.csv", "r2.csv"}


def test_templated_process_arg_mapping(tmp_path: Path):
    text = """
job: pam
variables: {strain: [ecoli]}
stages:
  - name: only
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out
    process_arg_mapping:
      collate:
        strain_col: "{strain}"
"""
    tasks = expand(text)
    assert tasks[0].process_arg_mapping == {"collate": {"strain_col": "ecoli"}}


def test_defaults_reference_earlier_defaults():
    text = """
job: d
variables: {tag: [T1]}
defaults:
  root: "/data/{tag}"
  processed: "{root}/processed"
stages:
  - name: only
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: "{processed}/out"
"""
    tasks = expand(text)
    assert tasks[0].output_dir == "/data/T1/processed/out"


def test_duplicate_stage_name_raises():
    text = """
job: dup
stages:
  - name: a
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out
  - name: a
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out
"""
    with pytest.raises(JobDefinitionError, match="duplicate stage name"):
        parse_job_definition(text)


def test_empty_variable_list_raises():
    text = """
job: bad
variables: {tag: []}
stages:
  - name: only
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out
"""
    with pytest.raises(JobDefinitionError, match="non-empty list"):
        parse_job_definition(text)


def test_unknown_fanout_type_raises():
    text = """
job: bad
stages:
  - name: only
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: telepathy}
    output_dir: /out
"""
    with pytest.raises(JobDefinitionError, match="unknown fanout type"):
        parse_job_definition(text)


def test_non_mapping_root_raises():
    with pytest.raises(JobDefinitionError, match="must be a mapping"):
        parse_job_definition("- a\n- b\n")


def test_missing_job_name_raises():
    text = """
stages:
  - name: only
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out
"""
    with pytest.raises(JobDefinitionError, match="'job' name"):
        parse_job_definition(text)


def test_no_stages_raises():
    with pytest.raises(JobDefinitionError, match="non-empty 'stages'"):
        parse_job_definition("job: x\n")


def test_mapping_file_missing_raises_job_definition_error(tmp_path: Path):
    text = f"""
job: m
stages:
  - name: prep
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {{type: mapping_file, mapping: "{(tmp_path / 'nope.yaml').as_posix()}"}}
    output_dir: /out
"""
    with pytest.raises(JobDefinitionError, match="could not read mapping file"):
        expand(text)


def test_folders_fanout_missing_dir_raises(tmp_path: Path):
    text = f"""
job: m
stages:
  - name: collate
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {{type: folders, data_dir: "{(tmp_path / 'missing').as_posix()}"}}
    output_dir: /out
"""
    with pytest.raises(JobDefinitionError, match="folders fan-out"):
        expand(text)


def test_lenient_preview_defers_downstream_missing_source(tmp_path: Path):
    text = f"""
job: lazy
stages:
  - name: prep
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {{type: none}}
    output_dir: "{tmp_path.as_posix()}/processed/x"
  - name: collate
    needs: [prep]
    pipeline_yaml: c.yaml
    pipeline: demo
    fanout: {{type: folders, data_dir: "{tmp_path.as_posix()}/processed"}}
    output_dir: "/out/{{item.name}}"
"""
    # Non-lenient expansion fails (the folder does not exist yet).
    with pytest.raises(JobDefinitionError):
        expand(text)

    # Lenient (preview) shows the downstream stage as a single deferred entry.
    tasks = expand(text, lenient=True)
    prep = [t for t in tasks if t.stage == "prep"]
    collate = [t for t in tasks if t.stage == "collate"]
    assert len(prep) == 1 and prep[0].deferred is False
    assert len(collate) == 1 and collate[0].deferred is True


def test_lenient_preview_still_errors_on_first_stage_missing_source(tmp_path: Path):
    # A first stage (no needs) with a missing source is a real error even in preview.
    text = f"""
job: bad
stages:
  - name: prep
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {{type: mapping_file, mapping: "{(tmp_path / 'missing.yaml').as_posix()}"}}
    output_dir: /out
"""
    with pytest.raises(JobDefinitionError):
        expand(text, lenient=True)
