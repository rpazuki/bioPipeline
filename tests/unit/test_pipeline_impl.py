from pathlib import Path

from pipeline.helpers import ensure_list, format_message, log_value, save_text, sequence


def test_ensure_list_handles_common_inputs() -> None:
    assert ensure_list(None) == []
    assert ensure_list((1, 2)) == [1, 2]
    assert ensure_list("x") == ["x"]


def test_sequence_builds_python_range_list() -> None:
    assert sequence(1, 5) == [1, 2, 3, 4]


def test_format_message_applies_prefix_suffix() -> None:
    assert format_message("core", prefix="[", suffix="]") == "[core]"


def test_log_value_returns_rendered_message() -> None:
    assert log_value("done", prefix="[pipeline] ") == "[pipeline] done"


def test_save_text_writes_file(tmp_path: Path) -> None:
    output = tmp_path / "logs" / "run.txt"
    returned = save_text("hello", str(output))
    assert output.read_text(encoding="utf-8") == "hello"
    assert Path(returned) == output.resolve()
