from pathlib import Path

import pytest

from pipeline.helpers import (
    download_file_to,
    download_temp_file,
    ensure_list,
    format_message,
    log_value,
    save_text,
    sequence,
)


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


def test_download_file_to_copies_local_source_into_output(tmp_path: Path) -> None:
    # Mirrors a staged input: the "url" is actually a local file path (a model
    # that a URL input field pre-downloaded into the run's inputs/ folder). The
    # file must be copied into the output dir so it ships with the results,
    # rather than being short-circuited and left behind under inputs/.
    staged = tmp_path / "inputs" / "default_organism_url" / "iML1515.xml"
    staged.parent.mkdir(parents=True)
    staged.write_text("<sbml/>", encoding="utf-8")
    out_dir = tmp_path / "outputs" / "data_root"

    returned = download_file_to(str(staged), str(out_dir))

    copied = out_dir / "iML1515.xml"
    assert copied.is_file()
    assert copied.read_text(encoding="utf-8") == "<sbml/>"
    assert Path(returned) == copied


def test_download_file_to_does_not_override_existing_output(tmp_path: Path) -> None:
    staged = tmp_path / "inputs" / "model.xml"
    staged.parent.mkdir(parents=True)
    staged.write_text("NEW", encoding="utf-8")
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()
    (out_dir / "model.xml").write_text("OLD", encoding="utf-8")

    returned = download_file_to(str(staged), str(out_dir))

    # Existing destination is preserved, so a re-run does not recopy.
    assert (out_dir / "model.xml").read_text(encoding="utf-8") == "OLD"
    assert Path(returned) == out_dir / "model.xml"


def test_download_file_to_missing_local_source_returns_none(tmp_path: Path) -> None:
    returned = download_file_to(str(tmp_path / "nope.xml"), str(tmp_path / "out"))
    assert returned is None


def test_download_file_to_downloads_remote_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pipeline.helpers.ops as ops

    class _FakeResponse:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def read(self) -> bytes:
            return self._data

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    monkeypatch.setattr(
        ops.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(b"<sbml/>")
    )
    out_dir = tmp_path / "outputs"

    returned = download_file_to("http://example.com/static/models/iML1515.xml", str(out_dir))

    saved = out_dir / "iML1515.xml"
    assert saved.is_file()
    assert saved.read_text(encoding="utf-8") == "<sbml/>"
    assert Path(returned) == saved


def test_download_temp_file_uses_url_basename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pipeline.helpers.ops as ops

    monkeypatch.setattr(ops.tempfile, "gettempdir", lambda: str(tmp_path))

    def _fake_urlretrieve(url: str, dest: Path) -> tuple[Path, None]:
        Path(dest).write_text("<sbml/>", encoding="utf-8")
        return Path(dest), None

    monkeypatch.setattr(ops.urllib.request, "urlretrieve", _fake_urlretrieve)

    returned = download_temp_file("http://example.com/static/models/iML1515.xml")

    saved = tmp_path / "iML1515.xml"
    assert saved.is_file()
    assert Path(returned) == saved
