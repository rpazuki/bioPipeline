from pathlib import Path

from bio_pipeline_manager.cli import main


VALID_YAML = """
pipelines:
  - demo:
      Inputs: []
      Processes: []
      Outputs: []
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

