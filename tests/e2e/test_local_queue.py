from pathlib import Path

from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.models import JobSpec, JobStatus
from bio_pipeline_manager.runner import LocalSubprocessRunner
from bio_pipeline_manager.storage import JobStore


def test_local_runner_executes_pipeline_via_engine(tmp_path: Path):
    out_file = tmp_path / "out" / "result.txt"
    yaml_path = tmp_path / "pipeline.yaml"
    yaml_path.write_text(
        f"""
pipelines:
  - demo:
      Inputs: []
      Processes:
        - saved:
            package: pipeline.helpers
            method: save_text
            parameters:
              text: "default text"
              path: "{out_file.as_posix()}"
      Outputs: []
""",
        encoding="utf-8",
    )

    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")
    job = queue.submit(
        JobSpec(
            yaml_path=yaml_path,
            pipeline_name="demo",
            output_dir=tmp_path / "out",
            # process_arg_mapping is the capability the old CLI runner could not express.
            process_arg_mapping={"saved": {"text": "overridden text"}},
        )
    )

    runner = LocalSubprocessRunner(store)
    result = runner.run(job.id)

    assert result.status == JobStatus.SUCCEEDED
    assert out_file.read_text(encoding="utf-8") == "overridden text"
    assert "Result payload" in job.log_path.read_text(encoding="utf-8")
