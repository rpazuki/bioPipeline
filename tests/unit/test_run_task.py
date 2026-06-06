"""Tests for the in-process Task runner entrypoint (run_task.py)."""

import json
from pathlib import Path

from bio_pipeline_manager.run_task import main, run_task


def _save_text_yaml(out_file: Path, *, method: str = "save_text") -> str:
    return f"""
pipelines:
  - demo:
      Inputs: []
      Processes:
        - step:
            package: pipeline.helpers
            method: {method}
            parameters: {{text: "done", path: "{out_file.as_posix()}"}}
      Outputs: []
"""


def _write_task(tmp_path: Path, yaml_text: str, **overrides) -> Path:
    yaml_path = tmp_path / "pipe.yaml"
    yaml_path.write_text(yaml_text, encoding="utf-8")
    task = {
        "yaml_path": str(yaml_path),
        "pipeline_name": "demo",
        "output_dir": str(tmp_path / "out"),
        "input_sources": {},
        "process_arg_mapping": {},
    }
    task.update(overrides)
    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")
    return task_path


def test_main_wrong_arg_count_returns_2():
    assert main([]) == 2
    assert main(["a", "b"]) == 2


def test_main_unreadable_task_file_returns_2(tmp_path: Path):
    assert main([str(tmp_path / "missing.json")]) == 2


def test_main_invalid_json_returns_2(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main([str(bad)]) == 2


def test_main_success_returns_0_and_prints_summary(tmp_path: Path, capsys):
    out_file = tmp_path / "result.txt"
    task_path = _write_task(tmp_path, _save_text_yaml(out_file))

    assert main([str(task_path)]) == 0
    assert out_file.read_text(encoding="utf-8") == "done"
    assert "Result payload" in capsys.readouterr().out


def test_main_task_failure_returns_1(tmp_path: Path):
    task_path = _write_task(tmp_path, _save_text_yaml(tmp_path / "x.txt", method="does_not_exist"))
    assert main([str(task_path)]) == 1


def test_run_task_applies_process_arg_mapping(tmp_path: Path):
    out_file = tmp_path / "result.txt"
    yaml_path = tmp_path / "pipe.yaml"
    yaml_path.write_text(_save_text_yaml(out_file), encoding="utf-8")
    run_task(
        {
            "yaml_path": str(yaml_path),
            "pipeline_name": "demo",
            "output_dir": str(tmp_path / "out"),
            "input_sources": {},
            "process_arg_mapping": {"step": {"text": "overridden"}},
        }
    )
    assert out_file.read_text(encoding="utf-8") == "overridden"
