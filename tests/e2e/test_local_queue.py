from pathlib import Path

from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.models import JobSpec, JobStatus
from bio_pipeline_manager.runner import LocalSubprocessRunner
from bio_pipeline_manager.storage import JobStore


def test_local_runner_executes_external_labutils_module(tmp_path: Path):
    fake_labutils = tmp_path / "fake_labutils"
    script_dir = fake_labutils / "labUtils" / "scripts"
    script_dir.mkdir(parents=True)
    (fake_labutils / "labUtils" / "__init__.py").write_text("", encoding="utf-8")
    (script_dir / "__init__.py").write_text("", encoding="utf-8")
    (script_dir / "run_a_pipeline.py").write_text(
        """
from pathlib import Path
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("yaml_file")
parser.add_argument("pipeline_name")
parser.add_argument("-o", "--output-dir", required=True)
parser.add_argument("-i", "--input", action="append", default=[])
args = parser.parse_args()

Path(args.output_dir).mkdir(parents=True, exist_ok=True)
Path(args.output_dir, "result.txt").write_text(
    f"{args.pipeline_name}\\n{args.yaml_file}\\n{args.input}\\n",
    encoding="utf-8",
)
print("fake labUtils completed")
""",
        encoding="utf-8",
    )

    yaml_path = tmp_path / "pipeline.yaml"
    yaml_path.write_text("pipelines: []\n", encoding="utf-8")
    store = JobStore(tmp_path / "state.sqlite")
    queue = JobQueue(store, tmp_path / "logs")
    job = queue.submit(
        JobSpec(
            yaml_path=yaml_path,
            pipeline_name="demo",
            output_dir=tmp_path / "out",
            input_sources={"raw": "raw.csv"},
        )
    )

    runner = LocalSubprocessRunner(store, extra_env={"PYTHONPATH": str(fake_labutils)})
    result = runner.run(job.id)

    assert result.status == JobStatus.SUCCEEDED
    assert (tmp_path / "out" / "result.txt").read_text(encoding="utf-8").startswith("demo")
    assert "fake labUtils completed" in job.log_path.read_text(encoding="utf-8")

