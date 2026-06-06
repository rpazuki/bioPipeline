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
    # Lazy: only `first` materialises at submit; `second` appears after it succeeds.
    assert [r.spec.stage for r in records] == ["first"]
    first = records[0]
    assert first.spec.depends_on == []

    # Pass 1: `first` runs; `second` is not materialised yet.
    ran = queue.run_due()
    assert [r.spec.stage for r in ran] == ["first"]
    assert file_a.exists()
    assert not file_b.exists()

    # Pass 2: `first` succeeded, so `second` is materialised and run.
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
    first = records[0]

    queue.run_due()  # first runs and fails
    assert store.get_job(first.id).status == JobStatus.FAILED

    queue.run_due()  # failed upstream -> `second` is materialised as a BLOCKED placeholder
    seconds = [j for j in store.list_jobs_by_parent(parent_id) if j.spec.stage == "second"]
    assert len(seconds) == 1
    assert seconds[0].status == JobStatus.BLOCKED
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

    # Drain to a fixed point (run_due is serial here, and stages materialise
    # lazily across passes), so iterate enough times to settle.
    for _ in range(10):
        queue.run_due()

    summary = queue.group_status(parent_id)
    # A: first+second succeeded; B: first failed, second blocked.
    assert summary["counts"].get("succeeded") == 2
    assert summary["counts"].get("failed") == 1
    assert summary["counts"].get("blocked") == 1
    assert summary["status"] == "partially_failed"


def test_lazy_folders_fanout_over_upstream_output(tmp_path: Path):
    """A `folders` fan-out whose directory is produced by an upstream stage:
    submit must succeed even though the directory does not exist yet, and the
    downstream stage materialises after the upstream runs."""
    processed = tmp_path / "run" / "processed"
    prep_yaml = tmp_path / "prep.yaml"
    collate_yaml = tmp_path / "collate.yaml"
    prep_yaml.write_text(_save_text_yaml(tmp_path / "prep_done.txt"), encoding="utf-8")
    collate_yaml.write_text(_save_text_yaml(tmp_path / "collate_done.txt"), encoding="utf-8")

    text = f"""
job: lazy_demo
stages:
  - name: prep
    pipeline_yaml: "{prep_yaml.as_posix()}"
    pipeline: demo
    fanout: {{type: none}}
    output_dir: "{processed.as_posix()}/sampleA"
  - name: collate
    needs: [prep]
    pipeline_yaml: "{collate_yaml.as_posix()}"
    pipeline: demo
    fanout: {{type: folders, data_dir: "{processed.as_posix()}"}}
    output_dir: "{tmp_path.as_posix()}/collated/{{item.name}}"
    input_sources: {{folder: "{{item.path}}"}}
"""
    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")

    # Submit succeeds even though `processed/` does not exist yet.
    parent_id, records = queue.submit_definition(text, yaml_resolver=Path)
    assert [r.spec.stage for r in records] == ["prep"]

    queue.run_due()  # prep runs and creates processed/sampleA
    assert (processed / "sampleA").exists()

    ran = queue.run_due()  # collate now fans out over the produced folder
    collate = [r for r in store.list_jobs_by_parent(parent_id) if r.spec.stage == "collate"]
    assert len(collate) == 1
    assert collate[0].spec.input_sources == {"folder": str(processed / "sampleA")}
    assert collate[0].status == JobStatus.SUCCEEDED
    assert [r.spec.stage for r in ran] == ["collate"]
    assert queue.group_status(parent_id)["status"] == "succeeded"


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
