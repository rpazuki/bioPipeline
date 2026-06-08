from __future__ import annotations

from pathlib import Path

import pytest

from bio_pipeline_manager.shared_storage import SharedStorage, SharedStorageError


def _store(tmp_path: Path) -> tuple[SharedStorage, Path]:
    root = tmp_path / "share"
    (root / "plate1").mkdir(parents=True)
    (root / "a.csv").write_text("x", encoding="utf-8")
    (root / "plate1" / "b.csv").write_text("y", encoding="utf-8")
    store = SharedStorage([{"id": "r1", "label": "Share One", "path": str(root)}])
    return store, root


def test_browse_lists_directories_first(tmp_path: Path):
    store, _ = _store(tmp_path)
    entries = store.browse("r1", "")
    assert entries[0].kind == "directory"  # directories sort before files
    assert {(e.name, e.kind) for e in entries} == {("plate1", "directory"), ("a.csv", "file")}
    assert [e.name for e in store.browse("r1", "plate1")] == ["b.csv"]


def test_browse_and_resolve_reject_escapes(tmp_path: Path):
    store, _ = _store(tmp_path)
    with pytest.raises(SharedStorageError):
        store.browse("r1", "../")
    with pytest.raises(SharedStorageError):
        store.resolve("r1", "../secret")
    with pytest.raises(SharedStorageError):
        store.resolve("r1", "/etc/passwd")
    with pytest.raises(SharedStorageError):
        store.browse("unknown-root", "")


def test_resolve_returns_absolute_path(tmp_path: Path):
    store, root = _store(tmp_path)
    assert store.resolve("r1", "plate1/b.csv") == (root / "plate1" / "b.csv").resolve()
    with pytest.raises(SharedStorageError):
        store.resolve("r1", "missing.csv")
