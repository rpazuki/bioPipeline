from pathlib import Path

import pytest

from bio_pipeline_manager.cli import _parse_inputs, _parse_process_args, main


VALID_YAML = """
pipelines:
  - demo:
      Inputs: []
      Processes: []
      Outputs: []
"""


DEFINITION = """
job: cli_demo
variables: {tag: [T1]}
stages:
  - name: only
    pipeline_yaml: demo
    pipeline: demo
    fanout: {type: none}
    output_dir: /out/{tag}
"""


def test_cli_template_show(capsys):
    result = main(["template", "show", "empty"])

    assert result == 0
    assert "new_pipeline" in capsys.readouterr().out


def test_cli_yaml_validate(tmp_path: Path, capsys):
    source = tmp_path / "demo.yaml"
    source.write_text(VALID_YAML, encoding="utf-8")

    assert main(["--home", str(tmp_path / "home"), "yaml", "save", "demo", str(source)]) == 0
    assert main(["--home", str(tmp_path / "home"), "yaml", "validate", "demo"]) == 0

    assert "valid" in capsys.readouterr().out


def test_parse_inputs_and_process_args():
    assert _parse_inputs(["raw=a.csv", "meta=b.csv"]) == {"raw": "a.csv", "meta": "b.csv"}
    assert _parse_process_args(["step.threshold=0.5", "step.window=3"]) == {
        "step": {"threshold": "0.5", "window": "3"}
    }


def test_parse_process_args_rejects_bad_format():
    with pytest.raises(ValueError, match="PROCESS.KEY=VALUE"):
        _parse_process_args(["missing_dot=1"])


def test_cli_job_preview(tmp_path: Path, capsys):
    definition = tmp_path / "def.yaml"
    definition.write_text(DEFINITION, encoding="utf-8")

    assert main(["--home", str(tmp_path / "home"), "job", "preview", str(definition)]) == 0
    out = capsys.readouterr().out
    assert "1 task(s)" in out
    assert "[only]" in out


def test_cli_job_submit_and_status(tmp_path: Path, capsys):
    home = str(tmp_path / "home")
    source = tmp_path / "demo.yaml"
    source.write_text(VALID_YAML, encoding="utf-8")
    definition = tmp_path / "def.yaml"
    definition.write_text(DEFINITION, encoding="utf-8")

    assert main(["--home", home, "yaml", "save", "demo", str(source)]) == 0
    capsys.readouterr()

    assert main(["--home", home, "job", "submit", str(definition)]) == 0
    submit_out = capsys.readouterr().out
    parent_id = submit_out.split()[0]
    assert "1 tasks queued" in submit_out

    assert main(["--home", home, "job", "status", parent_id]) == 0
    status_out = capsys.readouterr().out
    assert "cli_demo" in status_out
    assert "queued" in status_out


def test_cli_env_list(tmp_path: Path, capsys):
    assert main(["--home", str(tmp_path / "home"), "env", "list"]) == 0
    out = capsys.readouterr().out
    assert "==" in out  # name==version lines


def test_cli_env_install(tmp_path: Path, capsys, monkeypatch):
    def fake(python_executable, args):
        return 0, "ok", ""

    monkeypatch.setattr("bio_pipeline_manager.packages._default_pip_runner", fake)

    assert main(["--home", str(tmp_path / "home"), "env", "install", "pytest"]) == 0
    assert "install pytest" in capsys.readouterr().out


