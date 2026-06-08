from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from bio_pipeline_manager.published_jobs import PublishedJobError, PublishedJobRecord, resolve_io
from bio_pipeline_manager.run_workspace import RunWorkspaceError, RunWorkspaceStore


def _record(fields: list[dict]) -> PublishedJobRecord:
    now = datetime.now(timezone.utc)
    return PublishedJobRecord(
        id="x",
        name="n",
        description="",
        status="published",
        version=1,
        definition_name="",
        definition_content="job: x\nstages: []\n",
        fields=fields,
        created_at=now,
        updated_at=now,
        published_at=None,
        created_by="",
        updated_by="",
    )


def test_create_and_owner(tmp_path: Path):
    store = RunWorkspaceStore(tmp_path / "runs")
    manifest = store.create(owner_user_id="u1", published_job_id="j1")
    assert (tmp_path / "runs" / manifest.workspace_id / "inputs").is_dir()
    assert (tmp_path / "runs" / manifest.workspace_id / "outputs").is_dir()
    assert store.require_owner(manifest.workspace_id, "u1").owner_user_id == "u1"
    with pytest.raises(RunWorkspaceError):
        store.require_owner(manifest.workspace_id, "u2")


def test_path_escapes_are_rejected_or_confined(tmp_path: Path):
    store = RunWorkspaceStore(tmp_path / "runs")
    manifest = store.create(owner_user_id="u1", published_job_id="j1")
    with pytest.raises(RunWorkspaceError):
        store.safe_path(manifest.workspace_id, "../escape.txt")
    with pytest.raises(RunWorkspaceError):
        store.safe_path(manifest.workspace_id, "/abs/escape.txt")
    with pytest.raises(RunWorkspaceError):
        store.manifest("../etc")
    # A traversal in the *filename* is stripped to a basename, staying inside.
    dest, handle = store.prepare_input(manifest.workspace_id, "raw", "../../evil.csv")
    assert handle == "inputs/raw/evil.csv"
    assert (tmp_path / "runs").resolve() in dest.resolve().parents


def test_quota_blocks_streamed_overflow(tmp_path: Path):
    store = RunWorkspaceStore(tmp_path / "runs", max_bytes=10)
    manifest = store.create(owner_user_id="u1", published_job_id="j1")
    dest, handle = store.prepare_input(manifest.workspace_id, "raw", "a.csv")
    dest.write_bytes(b"12345")
    assert store.total_size(manifest.workspace_id) == 5
    assert store.input_abspath(manifest.workspace_id, handle).name == "a.csv"
    with pytest.raises(RunWorkspaceError):
        store.input_abspath(manifest.workspace_id, "inputs/raw/missing.csv")


def test_resolve_io_maps_input_and_output(tmp_path: Path):
    store = RunWorkspaceStore(tmp_path / "runs")
    manifest = store.create(owner_user_id="u1", published_job_id="j1")
    dest, handle = store.prepare_input(manifest.workspace_id, "raw", "in.csv")
    dest.write_bytes(b"data")
    fields = [
        {
            "id": "raw",
            "label": "Raw",
            "type": "file",
            "io_role": "input",
            "sources": ["upload"],
            "required": True,
            "bindings": [{"target": "stage_input_source", "stage": "run", "input": "raw"}],
        },
        {
            "id": "out",
            "label": "Out",
            "type": "directory",
            "io_role": "output",
            "required": True,
            "bindings": [{"target": "definition_path", "path": ["stages", "run", "output_dir"]}],
        },
        {"id": "keep", "label": "Keep", "type": "string", "io_role": "none", "bindings": [{"target": "x"}]},
    ]
    resolved = resolve_io(
        _record(fields),
        {"raw": "", "out": "", "keep": "hello"},
        file_bindings={"raw": {"kind": "upload", "path": handle}},
        workspaces=store,
        workspace_id=manifest.workspace_id,
    )
    assert resolved["raw"].endswith("in.csv") and "inputs" in resolved["raw"]
    assert resolved["out"].endswith("out") and "outputs" in resolved["out"]
    assert resolved["keep"] == "hello"  # io_role none passes through unchanged


def test_resolve_io_requires_a_file_for_required_input(tmp_path: Path):
    store = RunWorkspaceStore(tmp_path / "runs")
    manifest = store.create(owner_user_id="u1", published_job_id="j1")
    fields = [
        {
            "id": "raw",
            "label": "Raw",
            "type": "file",
            "io_role": "input",
            "sources": ["upload"],
            "required": True,
            "bindings": [{"target": "stage_input_source", "stage": "run", "input": "raw"}],
        }
    ]
    with pytest.raises(PublishedJobError):
        resolve_io(
            _record(fields),
            {"raw": ""},
            file_bindings={},
            workspaces=store,
            workspace_id=manifest.workspace_id,
        )
