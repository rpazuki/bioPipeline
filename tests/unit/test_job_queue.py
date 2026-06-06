"""Dependency-wiring tests for JobQueue.submit_definition (no execution)."""

from pathlib import Path

from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.storage import JobStore


TWO_CELL_CHAIN = """
job: chain
variables:
  tag: [A, B]
stages:
  - name: first
    pipeline_yaml: a.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out/{tag}/a
  - name: second
    needs: [first]
    pipeline_yaml: b.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out/{tag}/b
"""


def _queue(tmp_path: Path) -> JobQueue:
    store = JobStore(tmp_path / "state.sqlite")
    return JobQueue(store, tmp_path / "logs")


def test_dependencies_isolated_per_matrix_cell(tmp_path: Path):
    queue = _queue(tmp_path)
    _parent, records = queue.submit_definition(TWO_CELL_CHAIN, yaml_resolver=Path)

    by_key = {(r.spec.stage, r.spec.matrix_key["tag"]): r for r in records}
    first_a = by_key[("first", "A")]
    first_b = by_key[("first", "B")]
    second_a = by_key[("second", "A")]
    second_b = by_key[("second", "B")]

    # Each cell's `second` depends only on its own `first`.
    assert second_a.spec.depends_on == [first_a.id]
    assert second_b.spec.depends_on == [first_b.id]
    assert first_b.id not in second_a.spec.depends_on
    assert first_a.id not in second_b.spec.depends_on
    assert first_a.spec.depends_on == []


def test_downstream_depends_on_all_fanout_tasks(tmp_path: Path):
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text("r1.csv: m1.csv\nr2.csv: m2.csv\n", encoding="utf-8")
    text = f"""
job: m
stages:
  - name: prep
    pipeline_yaml: a.yaml
    pipeline: demo
    fanout: {{type: mapping_file, mapping: "{mapping.as_posix()}"}}
    output_dir: /out/{{item.stem}}
  - name: collate
    needs: [prep]
    pipeline_yaml: b.yaml
    pipeline: demo
    fanout: {{type: none}}
    output_dir: /out/STRAINS
"""
    queue = _queue(tmp_path)
    _parent, records = queue.submit_definition(text, yaml_resolver=Path)

    prep_ids = {r.id for r in records if r.spec.stage == "prep"}
    collate = next(r for r in records if r.spec.stage == "collate")
    assert len(prep_ids) == 2
    assert set(collate.spec.depends_on) == prep_ids
