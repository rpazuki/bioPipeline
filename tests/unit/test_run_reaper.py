from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.models import utc_now
from bio_pipeline_manager.published_jobs import PublishedJobStore
from bio_pipeline_manager.recurring_schedule import RecurringScheduleStore
from bio_pipeline_manager.run_reaper import RunReaper
from bio_pipeline_manager.run_workspace import RunWorkspaceStore
from bio_pipeline_manager.shared_storage import SharedStorage
from bio_pipeline_manager.storage import JobStore


def _terminal(_parent_job_id: str) -> dict:
    return {"status": "succeeded"}


def _save_text_yaml(out_file: Path) -> str:
    return (
        "pipelines:\n"
        "  - demo:\n"
        "      Inputs: []\n"
        "      Processes:\n"
        "        - step:\n"
        "            package: pipeline.helpers\n"
        "            method: save_text\n"
        "            parameters:\n"
        '              text: "done"\n'
        f'              path: "{out_file.as_posix()}"\n'
        "      Outputs: []\n"
    )


def test_reaper_retains_inputs_then_ttl_deletes_workspace(tmp_path: Path):
    store = PublishedJobStore(tmp_path / "state.sqlite")
    workspaces = RunWorkspaceStore(tmp_path / "runs")
    manifest = workspaces.create(owner_user_id="u1", published_job_id="missing-job")
    wid = manifest.workspace_id
    # one input (retained until the TTL) and one output (packaged then raw-cleared)
    dest, _ = workspaces.prepare_input(wid, "raw", "in.csv")
    dest.write_bytes(b"in")
    (workspaces.output_dir(wid, "result") / "out.csv").write_text("done", encoding="utf-8")
    store.create_run(
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
    # Inputs are retained (within the TTL window) so the run can still be rewound.
    assert workspaces.has_inputs(wid)
    assert not any((tmp_path / "runs" / wid / "outputs").iterdir())  # raw outputs dropped
    assert workspaces.reaped_at(wid) is not None

    # Past the TTL the whole workspace is removed to reclaim disk (no schedule).
    (tmp_path / "runs" / wid / ".reaped").write_text((utc_now() - timedelta(hours=25)).isoformat(), encoding="utf-8")
    reaper.reap_once()
    assert not workspaces.exists(wid)


def test_reaper_waits_for_lazily_materialised_downstream_stage(tmp_path: Path):
    """End-to-end guard against the premature-reap race: a multi-stage run whose
    upstream stage finishes before its dependant has materialised must NOT be
    packaged/settled until the downstream stage has actually produced its outputs.

    Mirrors the real failure: stage one writes outside the workspace (empty
    ``outputs/`` at that instant), stage two — materialised lazily one pass later —
    writes the artifact into the workspace.
    """
    state = tmp_path / "state.sqlite"
    queue = JobQueue(JobStore(state), tmp_path / "logs")
    workspaces = RunWorkspaceStore(tmp_path / "runs")
    manifest = workspaces.create(owner_user_id="u1", published_job_id="job1")
    wid = manifest.workspace_id
    result_dir = workspaces.output_dir(wid, "result")  # under the workspace's outputs/

    a_yaml = tmp_path / "a.yaml"
    b_yaml = tmp_path / "b.yaml"
    a_yaml.write_text(_save_text_yaml(tmp_path / "outside.txt"), encoding="utf-8")  # outside workspace
    b_yaml.write_text(_save_text_yaml(result_dir / "out.txt"), encoding="utf-8")  # into workspace outputs
    definition = (
        "job: chain\n"
        "stages:\n"
        "  - name: first\n"
        f'    pipeline_yaml: "{a_yaml.as_posix()}"\n'
        "    pipeline: demo\n"
        "    fanout: {type: none}\n"
        f'    output_dir: "{(tmp_path / "first").as_posix()}"\n'
        "  - name: second\n"
        "    needs: [first]\n"
        f'    pipeline_yaml: "{b_yaml.as_posix()}"\n'
        "    pipeline: demo\n"
        "    fanout: {type: none}\n"
        f'    output_dir: "{result_dir.as_posix()}"\n'
    )
    parent_id, _ = queue.submit_definition(definition, yaml_resolver=Path)

    runs = PublishedJobStore(state)
    runs.create_run(
        published_job_id="job1",
        published_version=1,
        user_id="u1",
        values={},
        rendered_definition=definition,
        parent_job_id=parent_id,
        workspace_id=wid,
    )
    reaper = RunReaper(
        published_jobs=runs,
        run_workspaces=workspaces,
        shared_storage=SharedStorage([]),
        group_status=queue.group_status,  # the real rollup, not a stub
    )

    # Pass 1: `first` succeeds; `second` not materialised yet. The reaper must wait.
    queue.run_due()
    reaper.reap_once()
    assert not workspaces.has_artifact(wid)
    assert workspaces.reaped_at(wid) is None

    # Pass 2: `second` materialises, runs and writes into the workspace; now reaping
    # packages the real outputs.
    queue.run_due()
    reaper.reap_once()
    assert workspaces.has_artifact(wid)
    import zipfile

    names = zipfile.ZipFile(workspaces.artifact_path(wid)).namelist()
    assert "result/out.txt" in names


def test_active_schedule_template_is_protected_until_it_finishes(tmp_path: Path):
    store = PublishedJobStore(tmp_path / "state.sqlite")
    workspaces = RunWorkspaceStore(tmp_path / "runs")
    schedules = RecurringScheduleStore(tmp_path / "state.sqlite")
    template = workspaces.create(owner_user_id="u1", published_job_id="job1")
    dest, _ = workspaces.prepare_input(template.workspace_id, "raw", "in.csv")
    dest.write_bytes(b"in")
    schedule = schedules.create(
        user_id="u1",
        published_job_id="job1",
        published_version=1,
        values={},
        file_bindings={},
        template_workspace_id=template.workspace_id,
        every_n=1,
        unit="days",
        ends_mode="count",
        ends_count=5,
        ends_at=None,
        first_run_at=utc_now(),
    )

    reaper = RunReaper(
        published_jobs=store,
        run_workspaces=workspaces,
        shared_storage=SharedStorage([]),
        group_status=_terminal,
        ttl_hours=24.0,
        recurring_schedules=schedules,
    )

    # The template is not a run; while the schedule is active it is never reaped.
    reaper.reap_once()
    assert workspaces.exists(template.workspace_id)

    # Once the schedule is stopped, the template gets the normal TTL (clocked from
    # creation, since it never ran) and is then removed.
    schedules.set_active(schedule.id, False)
    reaper.reap_once()
    assert workspaces.exists(template.workspace_id)  # still within TTL

    with schedules.connect() as conn:
        conn.execute(
            "UPDATE recurring_schedules SET created_at = ? WHERE id = ?",
            ((utc_now() - timedelta(hours=25)).isoformat(), schedule.id),
        )
    reaper.reap_once()
    assert not workspaces.exists(template.workspace_id)


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
