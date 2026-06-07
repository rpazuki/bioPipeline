from pathlib import Path

import pytest

from bio_pipeline_manager.job_definition import JobDefinitionError
from bio_pipeline_manager.job_definition_store import JobDefinitionStore

VALID = """
job: growth_full
stages:
  - name: only
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out
"""


def _store(tmp_path: Path) -> JobDefinitionStore:
    return JobDefinitionStore(tmp_path / "job_defs", tmp_path / "job_defs_archive")


def test_save_load_and_summary(tmp_path: Path):
    store = _store(tmp_path)
    store.save("demo.yaml", VALID)

    assert store.load("demo.yaml") == VALID
    assert store.job_name("demo.yaml") == "growth_full"
    assert store.summary("demo.yaml") == ("growth_full", True, None)
    assert [store.relative_name(p) for p in store.list()] == ["demo.yaml"]


def test_save_rejects_invalid_definition(tmp_path: Path):
    store = _store(tmp_path)
    with pytest.raises(JobDefinitionError):
        store.save("bad.yaml", "job: x\n")  # no stages


def test_save_no_overwrite(tmp_path: Path):
    store = _store(tmp_path)
    store.save("demo.yaml", VALID)
    with pytest.raises(FileExistsError):
        store.save("demo.yaml", VALID)
    store.save("demo.yaml", VALID, overwrite=True)  # ok


def test_archive_and_restore(tmp_path: Path):
    store = _store(tmp_path)
    store.save("a/demo.yaml", VALID)

    store.archive("a/demo.yaml")
    assert store.list() == []  # gone from active
    assert [store.relative_archived_name(p) for p in store.list_archived()] == ["a/demo.yaml"]

    store.restore("a/demo.yaml")
    assert [store.relative_name(p) for p in store.list()] == ["a/demo.yaml"]
    assert store.list_archived() == []


def test_restore_conflict_when_active_exists(tmp_path: Path):
    store = _store(tmp_path)
    store.save("demo.yaml", VALID)
    store.archive("demo.yaml")
    store.save("demo.yaml", VALID)  # a new active one with the same name
    with pytest.raises(FileExistsError):
        store.restore("demo.yaml")


def test_archive_missing_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        _store(tmp_path).archive("nope.yaml")


def test_delete_active_and_archived(tmp_path: Path):
    store = _store(tmp_path)
    store.save("demo.yaml", VALID)
    store.delete_file("demo.yaml")
    assert store.list() == []

    store.save("other.yaml", VALID)
    store.archive("other.yaml")
    store.delete_file("other.yaml", archived=True)
    assert store.list_archived() == []


def test_move_file(tmp_path: Path):
    store = _store(tmp_path)
    store.save("a/demo.yaml", VALID)
    store.move_file("a/demo.yaml", "b/renamed.yaml")
    assert [store.relative_name(p) for p in store.list()] == ["b/renamed.yaml"]


def test_path_traversal_rejected(tmp_path: Path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.save("../escape.yaml", VALID)
