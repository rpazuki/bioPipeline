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
