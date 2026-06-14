from __future__ import annotations

from pathlib import Path

from bio_pipeline_manager.published_jobs import PublishedJobStore
from bio_pipeline_manager.run_reaper import RunReaper
from bio_pipeline_manager.run_workspace import RunWorkspaceStore
from bio_pipeline_manager.shared_storage import SharedStorage


def _terminal(_parent_job_id: str) -> dict:
    return {"status": "succeeded"}


def test_reaper_packages_outputs_retains_inputs_and_keeps_workspace(tmp_path: Path):
    store = PublishedJobStore(tmp_path / "state.sqlite")
    workspaces = RunWorkspaceStore(tmp_path / "runs")
    manifest = workspaces.create(owner_user_id="u1", published_job_id="missing-job")
    wid = manifest.workspace_id
    # one input (now RETAINED for replay) and one output (packaged then raw-cleared)
    dest, _ = workspaces.prepare_input(wid, "raw", "in.csv")
    dest.write_bytes(b"in")
    (workspaces.output_dir(wid, "result") / "out.csv").write_text("done", encoding="utf-8")
    run = store.create_run(
        published_job_id="missing-job",
        published_version=1,
        user_id="u1",
        values={},
        rendered_definition="x",
        parent_job_id="p1",
        workspace_id=wid,
    )

    reaper = RunReaper(
        published_jobs=store,
        run_workspaces=workspaces,
        shared_storage=SharedStorage([]),
        group_status=_terminal,
        ttl_hours=24.0,
    )
    reaper.reap_once()

    assert workspaces.has_artifact(wid)
    # Inputs are retained so the run can be rewound / replayed by a recurring schedule.
    assert (tmp_path / "runs" / wid / "inputs" / "raw" / "in.csv").is_file()
    assert workspaces.has_inputs(wid)
    # Raw outputs are dropped (captured in artifact.zip) but the workspace survives.
    assert not any((tmp_path / "runs" / wid / "outputs").iterdir())
    assert workspaces.reaped_at(wid) is not None

    # A second pass is a no-op: already delivered, workspace + inputs still present.
    reaper.reap_once()
    assert workspaces.exists(wid)
    assert workspaces.has_inputs(wid)
    _ = run  # run row persists; its workspace is retained until the run is deleted


def test_reaper_shared_writes_output_to_allowlisted_root(tmp_path: Path):
    share = tmp_path / "share"
    share.mkdir()
    store = PublishedJobStore(tmp_path / "state.sqlite")
    workspaces = RunWorkspaceStore(tmp_path / "runs")
    shared = SharedStorage([{"id": "r1", "label": "Share", "path": str(share)}])

    definition = (
        "job: x\n"
        "stages:\n"
        "  - name: run\n"
        "    pipeline_yaml: a.yaml\n"
        "    pipeline: p\n"
        "    output_dir: /server/out\n"
    )
    field = {
        "id": "out",
        "label": "Out",
        "type": "directory",
        "io_role": "output",
        "delivery": ["shared"],
        "shared_roots": ["r1"],
        "bindings": [{"target": "definition_path", "path": ["stages", "run", "output_dir"]}],
    }
    record = store.create(
        name="x",
        description="",
        definition_name="",
        definition_content=definition,
        fields=[field],
        actor="admin",
        status="published",
    )
    manifest = workspaces.create(owner_user_id="u1", published_job_id=record.id)
    wid = manifest.workspace_id
    (workspaces.output_dir(wid, "out") / "result.csv").write_text("data", encoding="utf-8")
    run = store.create_run(
        published_job_id=record.id,
        published_version=record.version,
        user_id="u1",
        values={},
        rendered_definition="x",
        parent_job_id="p1",
        workspace_id=wid,
    )

    RunReaper(
        published_jobs=store,
        run_workspaces=workspaces,
        shared_storage=shared,
        group_status=_terminal,
    ).reap_once()

    written = share / "bio_pipeline_outputs" / run.id / "out" / "result.csv"
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == "data"
