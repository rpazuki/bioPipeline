"""Dependency-wiring tests for JobQueue.submit_definition (no execution)."""

from pathlib import Path

from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.models import JobStatus, utc_now
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


def _succeed(store: JobStore, record) -> None:
    store.update_status(record.id, JobStatus.SUCCEEDED, finished_at=utc_now())


def test_dependencies_isolated_per_matrix_cell(tmp_path: Path):
    queue = _queue(tmp_path)
    parent, records = queue.submit_definition(TWO_CELL_CHAIN, yaml_resolver=Path)

    # Only the first stage of each cell is materialised at submit.
    assert {(r.spec.stage, r.spec.matrix_key["tag"]) for r in records} == {("first", "A"), ("first", "B")}
    first_a = next(r for r in records if r.spec.matrix_key["tag"] == "A")
    first_b = next(r for r in records if r.spec.matrix_key["tag"] == "B")
    assert first_a.spec.depends_on == []

    # Once both firsts succeed, the seconds materialise, each depending only on
    # its own cell's first.
    _succeed(queue.store, first_a)
    _succeed(queue.store, first_b)
    new_records = queue._materialize_ready(parent)

    seconds = {r.spec.matrix_key["tag"]: r for r in new_records if r.spec.stage == "second"}
    assert seconds["A"].spec.depends_on == [first_a.id]
    assert seconds["B"].spec.depends_on == [first_b.id]
    assert first_b.id not in seconds["A"].spec.depends_on


def test_removed_group_task_is_not_resurrected(tmp_path: Path):
    """Deleting (or cancelling+deleting) a group's Task must not make the worker
    re-create and re-run it on the next run_due — the stage stays materialised."""
    queue = _queue(tmp_path)
    parent, records = queue.submit_definition(TWO_CELL_CHAIN, yaml_resolver=Path)

    # Materialise + complete every stage of cell A by hand (no real execution).
    first_a = next(r for r in records if r.spec.matrix_key["tag"] == "A")
    _succeed(queue.store, first_a)
    second_a = next(
        r for r in queue._materialize_ready(parent) if r.spec.matrix_key["tag"] == "A" and r.spec.stage == "second"
    )

    # Cancel then delete the downstream task.
    queue.cancel(second_a.id)
    queue.delete(second_a.id)
    assert not any(j.id == second_a.id for j in queue.store.list_jobs_by_parent(parent))

    # Re-materialising must NOT recreate stage `second` for cell A.
    for _ in range(3):
        queue._materialize_ready(parent)
    cell_a_second = [
        j for j in queue.store.list_jobs_by_parent(parent) if j.spec.matrix_key.get("tag") == "A" and j.spec.stage == "second"
    ]
    assert cell_a_second == []


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
    parent, records = queue.submit_definition(text, yaml_resolver=Path)

    prep_ids = {r.id for r in records if r.spec.stage == "prep"}
    assert len(prep_ids) == 2  # two mapping pairs; collate not yet materialised
    assert not any(r.spec.stage == "collate" for r in records)

    for record in records:
        _succeed(queue.store, record)
    new_records = queue._materialize_ready(parent)

    collate = next(r for r in new_records if r.spec.stage == "collate")
    assert set(collate.spec.depends_on) == prep_ids
