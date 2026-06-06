from pathlib import Path

from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.models import JobStatus
from bio_pipeline_manager.storage import JobStore


def _save_text_yaml(out_file: Path, *, package: str = "pipeline.helpers", method: str = "save_text") -> str:
    return f"""
pipelines:
  - demo:
      Inputs: []
      Processes:
        - step:
            package: {package}
            method: {method}
            parameters:
              text: "done"
              path: "{out_file.as_posix()}"
      Outputs: []
"""


def _definition(tmp_path: Path, a_yaml: Path, b_yaml: Path) -> str:
    return f"""
job: chain
variables:
  tag: [one]
defaults:
  root: "{tmp_path.as_posix()}/{{tag}}"
stages:
  - name: first
    pipeline_yaml: "{a_yaml.as_posix()}"
    pipeline: demo
    fanout: {{type: none}}
    output_dir: "{{root}}/a"
  - name: second
    needs: [first]
    pipeline_yaml: "{b_yaml.as_posix()}"
    pipeline: demo
    fanout: {{type: none}}
    output_dir: "{{root}}/b"
"""


def test_definition_runs_stages_in_dependency_order(tmp_path: Path):
    file_a = tmp_path / "a.txt"
    file_b = tmp_path / "b.txt"
    a_yaml = tmp_path / "a.yaml"
    b_yaml = tmp_path / "b.yaml"
    a_yaml.write_text(_save_text_yaml(file_a), encoding="utf-8")
    b_yaml.write_text(_save_text_yaml(file_b), encoding="utf-8")

    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")

    parent_id, records = queue.submit_definition(_definition(tmp_path, a_yaml, b_yaml), yaml_resolver=Path)
    assert len(records) == 2
    first = next(r for r in records if r.spec.stage == "first")
    second = next(r for r in records if r.spec.stage == "second")
    assert second.spec.depends_on == [first.id]
    assert first.spec.depends_on == []

    # Pass 1: only `first` is runnable (`second` waits on its dependency).
    ran = queue.run_due()
    assert [r.spec.stage for r in ran] == ["first"]
    assert file_a.exists()
    assert not file_b.exists()
    assert store.get_job(second.id).status == JobStatus.QUEUED

    # Pass 2: `first` succeeded, so `second` becomes runnable.
    ran = queue.run_due()
    assert [r.spec.stage for r in ran] == ["second"]
    assert file_b.exists()

    summary = queue.group_status(parent_id)
    assert summary["status"] == "succeeded"
    assert summary["counts"] == {"succeeded": 2}


def test_failed_dependency_blocks_downstream(tmp_path: Path):
    file_b = tmp_path / "b.txt"
    a_yaml = tmp_path / "a.yaml"
    b_yaml = tmp_path / "b.yaml"
    # `first` references a missing method, so it fails.
    a_yaml.write_text(_save_text_yaml(tmp_path / "a.txt", method="does_not_exist"), encoding="utf-8")
    b_yaml.write_text(_save_text_yaml(file_b), encoding="utf-8")

    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")
    parent_id, records = queue.submit_definition(_definition(tmp_path, a_yaml, b_yaml), yaml_resolver=Path)
    second = next(r for r in records if r.spec.stage == "second")

    queue.run_due()  # first runs and fails
    assert store.get_job(next(r.id for r in records if r.spec.stage == "first")).status == JobStatus.FAILED

    queue.run_due()  # second sees a failed dependency -> BLOCKED
    assert store.get_job(second.id).status == JobStatus.BLOCKED
    assert not file_b.exists()

    summary = queue.group_status(parent_id)
    assert summary["status"] == "failed"


def test_partial_failure_rollup_across_cells(tmp_path: Path):
    """One cell fails (blocking its downstream); the other cell fully succeeds."""
    ok_yaml = tmp_path / "ok.yaml"
    bad_yaml = tmp_path / "bad.yaml"
    ok_yaml.write_text(_save_text_yaml(tmp_path / "ok.txt"), encoding="utf-8")
    bad_yaml.write_text(_save_text_yaml(tmp_path / "bad.txt", method="does_not_exist"), encoding="utf-8")

    # tag A uses the good pipeline for both stages; tag B's first stage fails.
    text = f"""
job: mixed
variables:
  tag:
    - {{name: A, first_yaml: "{ok_yaml.as_posix()}"}}
    - {{name: B, first_yaml: "{bad_yaml.as_posix()}"}}
stages:
  - name: first
    pipeline_yaml: "{{tag.first_yaml}}"
    pipeline: demo
    fanout: {{type: none}}
    output_dir: "{tmp_path.as_posix()}/{{tag.name}}/a"
  - name: second
    needs: [first]
    pipeline_yaml: "{ok_yaml.as_posix()}"
    pipeline: demo
    fanout: {{type: none}}
    output_dir: "{tmp_path.as_posix()}/{{tag.name}}/b"
"""
    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")
    parent_id, _records = queue.submit_definition(text, yaml_resolver=Path)

    # Drain to a fixed point (first stages, then second/blocked resolution).
    for _ in range(4):
        queue.run_due()

    summary = queue.group_status(parent_id)
    # A: first+second succeeded; B: first failed, second blocked.
    assert summary["counts"].get("succeeded") == 2
    assert summary["counts"].get("failed") == 1
    assert summary["counts"].get("blocked") == 1
    assert summary["status"] == "partially_failed"


def test_parallel_run_due_executes_independent_tasks(tmp_path: Path):
    """Independent (no-dependency) tasks across cells run under a parallel drain."""
    yaml_path = tmp_path / "p.yaml"
    yaml_path.write_text(_save_text_yaml(tmp_path / "shared.txt"), encoding="utf-8")
    text = f"""
job: fanwide
variables:
  n: [1, 2, 3]
stages:
  - name: only
    pipeline_yaml: "{yaml_path.as_posix()}"
    pipeline: demo
    fanout: {{type: none}}
    output_dir: "{tmp_path.as_posix()}/out/{{n}}"
"""
    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")
    parent_id, records = queue.submit_definition(text, yaml_resolver=Path)
    assert len(records) == 3

    ran = queue.run_due(parallel=3)
    assert len(ran) == 3
    assert all(r.status == JobStatus.SUCCEEDED for r in ran)
    assert queue.group_status(parent_id)["status"] == "succeeded"
