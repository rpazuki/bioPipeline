from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_runtime
from app.main import app
from app.services.runtime import create_runtime
from auth_helpers import install_admin_override, install_user_override
from bio_pipeline_manager.auth_models import Role

PIPELINE_YAML = """
pipelines:
  - demo:
      Inputs: []
      Processes:
        - step:
            package: pipeline.helpers.ops
            method: return_value
            parameters:
              value: original
      Outputs:
        - step: result.txt
"""


JOB_DEF = """
job: public_demo
variables:
  tag: [A, B]
defaults:
  root: /tmp/base
stages:
  - name: run
    pipeline_yaml: demo.yaml
    pipeline: demo
    fanout: {type: none}
    process_arg_mapping:
      step:
        value: original
    output_dir: "{root}/{tag}"
"""


def _client(tmp_path: Path, shared_roots: list[dict] | None = None) -> TestClient:
    app.dependency_overrides.clear()
    get_runtime.cache_clear()
    runtime = create_runtime(tmp_path, shared_roots=shared_roots)
    user = runtime.auth.create_user(username="test-user", password="password123", role=Role.USER)
    app.dependency_overrides[get_runtime] = lambda: runtime
    install_admin_override(app)
    install_user_override(app, user_id=user.id)
    return TestClient(app)


def _field(field_id: str, label: str, binding: dict, field_type: str = "string", default="x") -> dict:
    return {
        "id": field_id,
        "label": label,
        "type": field_type,
        "required": True,
        "default": default,
        "help": f"Purpose of {label}",
        "example": str(default),
        "options": [],
        "bindings": [binding],
    }


def test_admin_inspects_and_publishes_user_safe_fields(tmp_path: Path):
    client = _client(tmp_path)
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})

    inspect = client.post("/api/v1/published-jobs/admin/inspect", json={"content": JOB_DEF})
    assert inspect.status_code == 200
    candidates = inspect.json()["candidates"]
    candidate_ids = {field["id"] for field in candidates}
    assert "var_tag" in candidate_ids
    assert "stage_run_process_step_value" in candidate_ids
    assert [field["label"] for field in candidates].count("run: step.value") == 1

    create = client.post(
        "/api/v1/published-jobs/admin",
        json={
            "name": "Public demo",
            "description": "User-facing demo",
            "definition_name": "public_demo.yaml",
            "definition_content": JOB_DEF,
            "status": "published",
            "fields": [
                _field(
                    "tag",
                    "Run tag",
                    {"target": "definition_path", "path": ["variables", "tag"]},
                    "enum",
                    "A",
                ),
                _field(
                    "value",
                    "Step value",
                    {"target": "stage_process_arg", "stage": "run", "process": "step", "parameter": "value"},
                    "integer",
                    1,
                ),
            ],
        },
    )
    assert create.status_code == 201
    job_id = create.json()["id"]

    public = client.get(f"/api/v1/published-jobs/catalog/{job_id}")
    assert public.status_code == 200
    assert public.json()["fields"][0]["help"] == "Purpose of Run tag"
    assert "bindings" not in public.json()["fields"][0]

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_user_submits_rewinds_and_sees_own_run(tmp_path: Path):
    client = _client(tmp_path)
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    create = client.post(
        "/api/v1/published-jobs/admin",
        json={
            "name": "Public demo",
            "definition_content": JOB_DEF,
            "status": "published",
            "fields": [
                _field("tag", "Run tag", {"target": "definition_path", "path": ["variables", "tag"]}, "string", "A"),
                _field(
                    "value",
                    "Step value",
                    {"target": "stage_process_arg", "stage": "run", "process": "step", "parameter": "value"},
                    "integer",
                    1,
                ),
            ],
        },
    )
    job_id = create.json()["id"]

    submitted = client.post(f"/api/v1/published-jobs/catalog/{job_id}/runs", json={"values": {"tag": "B", "value": 7}})
    assert submitted.status_code == 201
    run = submitted.json()
    assert run["published_job_name"] == "Public demo"
    assert run["total"] == 1
    Path(run["group"]["tasks"][0]["log_path"]).write_text("published run log\nline two\n", encoding="utf-8")

    runs = client.get("/api/v1/published-jobs/my-runs")
    assert runs.status_code == 200
    assert [item["id"] for item in runs.json()] == [run["id"]]

    detail = client.get(f"/api/v1/published-jobs/my-runs/{run['id']}")
    assert detail.status_code == 200
    task = detail.json()["group"]["tasks"][0]
    assert task["matrix_key"] == {"tag": "B"}
    assert task["process_arg_mapping"] == {"step": {"value": 7}}
    assert detail.json()["logs"][task["id"]] == "published run log\nline two\n"

    rewind = client.post(f"/api/v1/published-jobs/my-runs/{run['id']}/rewind")
    assert rewind.status_code == 201
    assert rewind.json()["values"] == {"tag": "B", "value": 7}

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


JOB_DEF_VARIANT = """
job: variant_demo
variables:
  variant:
    - {name: a, group_cols: well, pipeline: demo}
    - {name: b, group_cols: gid, pipeline: demo}
defaults:
  root: /tmp/base
stages:
  - name: run
    pipeline_yaml: demo.yaml
    pipeline: "{variant.pipeline}"
    fanout: {type: none}
    process_arg_mapping:
      step:
        value: "{variant.group_cols}"
    output_dir: "{root}/{variant.name}"
"""


def test_user_submits_variant_with_stale_option_missing_field(tmp_path: Path):
    # A variant enum whose stored option values predate a later-added field
    # ({variant.group_cols}) must still run: the submit reconciles the selection
    # against the current definition entry by name so the token resolves.
    client = _client(tmp_path)
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    create = client.post(
        "/api/v1/published-jobs/admin",
        json={
            "name": "Variant demo",
            "definition_content": JOB_DEF_VARIANT,
            "status": "published",
            "fields": [
                {
                    "id": "var_variant",
                    "label": "Variant",
                    "type": "enum",
                    "required": True,
                    "default": {"name": "a", "pipeline": "demo"},  # stale: no group_cols
                    "help": "Pick a variant",
                    "example": "a",
                    "options": [
                        {"label": "a", "value": {"name": "a", "pipeline": "demo"}},
                        {"label": "b", "value": {"name": "b", "pipeline": "demo"}},
                    ],
                    "bindings": [{"target": "definition_path", "path": ["variables", "variant"]}],
                }
            ],
        },
    )
    assert create.status_code == 201
    job_id = create.json()["id"]

    # Submit the (stale) "b" option — missing group_cols — through the full path.
    submitted = client.post(
        f"/api/v1/published-jobs/catalog/{job_id}/runs",
        json={"values": {"var_variant": {"name": "b", "pipeline": "demo"}}},
    )
    assert submitted.status_code == 201, submitted.text
    task = submitted.json()["group"]["tasks"][0]
    assert task["matrix_key"] == {"variant": "b"}
    # {variant.group_cols} resolved from the current definition entry, not the stale option.
    assert task["process_arg_mapping"] == {"step": {"value": "gid"}}

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_admin_lists_usage_validates_and_deletes_drafts(tmp_path: Path):
    client = _client(tmp_path)
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    create = client.post(
        "/api/v1/published-jobs/admin",
        json={
            "name": "Draft demo",
            "definition_content": JOB_DEF,
            "status": "draft",
            "fields": [
                _field("tag", "Run tag", {"target": "definition_path", "path": ["variables", "tag"]}, "string", "A"),
            ],
        },
    )
    assert create.status_code == 201
    draft_id = create.json()["id"]

    validate = client.post(f"/api/v1/published-jobs/admin/{draft_id}/validate")
    assert validate.status_code == 200
    assert validate.json()["field_count"] == 1
    assert validate.json()["run_count"] == 0

    delete = client.delete(f"/api/v1/published-jobs/admin/{draft_id}")
    assert delete.status_code == 204
    assert all(job["id"] != draft_id for job in client.get("/api/v1/published-jobs/admin").json())

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_admin_run_status_and_force_delete_used_job(tmp_path: Path):
    client = _client(tmp_path)
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    create = client.post(
        "/api/v1/published-jobs/admin",
        json={
            "name": "Used demo",
            "definition_content": JOB_DEF,
            "status": "published",
            "fields": [
                _field("tag", "Run tag", {"target": "definition_path", "path": ["variables", "tag"]}, "string", "A"),
            ],
        },
    )
    job_id = create.json()["id"]
    run = client.post(f"/api/v1/published-jobs/catalog/{job_id}/runs", json={"values": {"tag": "A"}})
    assert run.status_code == 201

    all_runs = client.get("/api/v1/published-jobs/admin/runs")
    assert all_runs.status_code == 200
    assert all_runs.json()[0]["published_job_id"] == job_id
    assert all_runs.json()[0]["username"] == "test-user"

    job_runs = client.get(f"/api/v1/published-jobs/admin/{job_id}/runs")
    assert job_runs.status_code == 200
    assert len(job_runs.json()) == 1

    blocked_delete = client.delete(f"/api/v1/published-jobs/admin/{job_id}")
    assert blocked_delete.status_code == 400

    forced_delete = client.delete(f"/api/v1/published-jobs/admin/{job_id}?force=true")
    assert forced_delete.status_code == 204

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


JOB_DEF_IO = """
job: io_demo
stages:
  - name: run
    pipeline_yaml: demo.yaml
    pipeline: demo
    fanout: {type: none}
    input_sources:
      raw_data: "/server/in.csv"
    output_dir: "/server/out/run"
"""


def test_admin_inspect_proposes_io_roles(tmp_path: Path):
    client = _client(tmp_path)
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})

    inspect = client.post("/api/v1/published-jobs/admin/inspect", json={"content": JOB_DEF_IO})
    assert inspect.status_code == 200
    by_id = {field["id"]: field for field in inspect.json()["candidates"]}

    # An input src is proposed as a researcher input accepting a file.
    raw = by_id["stage_run_input_raw_data"]
    assert raw["io_role"] == "input"
    assert raw["accept"] == "file"
    assert raw["sources"] == ["upload"]
    assert raw["delivery"] == []

    # A stage output_dir is proposed as a returned output directory.
    out = by_id["stage_run_output_dir"]
    assert out["io_role"] == "output"
    assert out["accept"] == "directory"
    assert out["delivery"] == ["download"]

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


JOB_DEF_UPLOAD = """
job: upload_demo
stages:
  - name: run
    pipeline_yaml: demo.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: "/server/out"
"""


def _io_field(field_id, label, binding, *, io_role, field_type, sources=None):
    return {
        "id": field_id,
        "label": label,
        "type": field_type,
        "required": True,
        "default": "",
        "help": label,
        "example": "",
        "options": [],
        "io_role": io_role,
        "sources": sources or [],
        "bindings": [binding],
    }


def test_user_uploads_input_then_executes_against_workspace(tmp_path: Path):
    client = _client(tmp_path)
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    create = client.post(
        "/api/v1/published-jobs/admin",
        json={
            "name": "Upload demo",
            "definition_content": JOB_DEF_UPLOAD,
            "status": "published",
            "fields": [
                _io_field(
                    "raw_data",
                    "Raw data",
                    {"target": "stage_input_source", "stage": "run", "input": "raw_data"},
                    io_role="input",
                    field_type="file",
                    sources=["upload"],
                ),
            ],
        },
    )
    assert create.status_code == 201
    job_id = create.json()["id"]

    # Executing a required upload field with no file is rejected.
    missing = client.post(f"/api/v1/published-jobs/catalog/{job_id}/runs", json={"values": {"raw_data": ""}})
    assert missing.status_code == 400

    draft = client.post(f"/api/v1/published-jobs/catalog/{job_id}/runs/draft")
    assert draft.status_code == 201
    workspace_id = draft.json()["workspace_id"]

    upload = client.post(
        f"/api/v1/published-jobs/catalog/{job_id}/runs/{workspace_id}/uploads/raw_data?filename=sample.csv",
        content=b"col\n1\n",
    )
    assert upload.status_code == 201
    handle = upload.json()["handle"]
    assert handle == "inputs/raw_data/sample.csv"

    run = client.post(
        f"/api/v1/published-jobs/catalog/{job_id}/runs",
        json={
            "values": {"raw_data": ""},
            "workspace_id": workspace_id,
            "file_bindings": {"raw_data": {"kind": "upload", "path": handle}},
        },
    )
    assert run.status_code == 201
    detail = run.json()
    assert detail["workspace_id"] == workspace_id
    # The materialised task's input source points at the uploaded file in the workspace.
    raw_source = detail["group"]["tasks"][0]["input_sources"]["raw_data"].replace("\\", "/")
    assert raw_source.endswith("inputs/raw_data/sample.csv")

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_user_browses_shared_root_then_executes(tmp_path: Path):
    share = tmp_path / "share"
    (share / "plate1").mkdir(parents=True)
    (share / "plate1" / "raw.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    client = _client(tmp_path, shared_roots=[{"id": "ecoli", "label": "E. coli data", "path": str(share)}])
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    field = _io_field(
        "raw_data",
        "Raw data",
        {"target": "stage_input_source", "stage": "run", "input": "raw_data"},
        io_role="input",
        field_type="file",
        sources=["shared"],
    )
    field["shared_roots"] = ["ecoli"]
    create = client.post(
        "/api/v1/published-jobs/admin",
        json={"name": "Shared demo", "definition_content": JOB_DEF_UPLOAD, "status": "published", "fields": [field]},
    )
    assert create.status_code == 201
    job_id = create.json()["id"]

    roots = client.get(f"/api/v1/published-jobs/catalog/{job_id}/shared-roots")
    assert roots.status_code == 200
    assert roots.json() == [{"id": "ecoli", "label": "E. coli data"}]

    top = client.get(
        f"/api/v1/published-jobs/catalog/{job_id}/browse",
        params={"field": "raw_data", "root": "ecoli"},
    )
    assert top.status_code == 200
    assert any(entry["name"] == "plate1" and entry["kind"] == "directory" for entry in top.json()["entries"])

    inside = client.get(
        f"/api/v1/published-jobs/catalog/{job_id}/browse",
        params={"field": "raw_data", "root": "ecoli", "subpath": "plate1"},
    )
    assert [entry["name"] for entry in inside.json()["entries"]] == ["raw.csv"]

    # Escaping the root is rejected.
    escape = client.get(
        f"/api/v1/published-jobs/catalog/{job_id}/browse",
        params={"field": "raw_data", "root": "ecoli", "subpath": "../"},
    )
    assert escape.status_code == 400

    # Execute with the picked shared path (no upload/workspace needed).
    run = client.post(
        f"/api/v1/published-jobs/catalog/{job_id}/runs",
        json={
            "values": {"raw_data": ""},
            "file_bindings": {"raw_data": {"kind": "shared", "root": "ecoli", "path": "plate1/raw.csv"}},
        },
    )
    assert run.status_code == 201
    raw_source = run.json()["group"]["tasks"][0]["input_sources"]["raw_data"].replace("\\", "/")
    assert raw_source.endswith("plate1/raw.csv")

    # A root the field does not allow is rejected.
    bad = client.post(
        f"/api/v1/published-jobs/catalog/{job_id}/runs",
        json={
            "values": {"raw_data": ""},
            "file_bindings": {"raw_data": {"kind": "shared", "root": "other", "path": "x"}},
        },
    )
    assert bad.status_code == 400

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_output_run_packages_and_downloads_artifact(tmp_path: Path):
    import io
    import zipfile

    client = _client(tmp_path)
    runtime = app.dependency_overrides[get_runtime]()
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    field = _io_field(
        "out",
        "Results",
        {"target": "definition_path", "path": ["stages", "run", "output_dir"]},
        io_role="output",
        field_type="directory",
    )
    field["accept"] = "directory"
    create = client.post(
        "/api/v1/published-jobs/admin",
        json={"name": "Output demo", "definition_content": JOB_DEF_UPLOAD, "status": "published", "fields": [field]},
    )
    job_id = create.json()["id"]
    workspace_id = client.post(f"/api/v1/published-jobs/catalog/{job_id}/runs/draft").json()["workspace_id"]
    run = client.post(
        f"/api/v1/published-jobs/catalog/{job_id}/runs",
        json={"values": {"out": ""}, "workspace_id": workspace_id},
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    # Simulate the job having written an output, then package as the reaper would.
    (runtime.run_workspaces.output_dir(workspace_id, "out") / "result.csv").write_text("ok", encoding="utf-8")
    runtime.run_workspaces.package_outputs(workspace_id)

    detail = client.get(f"/api/v1/published-jobs/my-runs/{run_id}").json()
    assert detail["artifact_available"] is True

    download = client.get(f"/api/v1/published-jobs/my-runs/{run_id}/artifact")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    assert "out/result.csv" in zipfile.ZipFile(io.BytesIO(download.content)).namelist()

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_chunked_upload_appends_by_offset(tmp_path: Path):
    client = _client(tmp_path)
    runtime = app.dependency_overrides[get_runtime]()
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    field = _io_field(
        "raw_data",
        "Raw",
        {"target": "stage_input_source", "stage": "run", "input": "raw_data"},
        io_role="input",
        field_type="file",
        sources=["upload"],
    )
    job_id = client.post(
        "/api/v1/published-jobs/admin",
        json={"name": "Chunk demo", "definition_content": JOB_DEF_UPLOAD, "status": "published", "fields": [field]},
    ).json()["id"]
    workspace_id = client.post(f"/api/v1/published-jobs/catalog/{job_id}/runs/draft").json()["workspace_id"]
    base = f"/api/v1/published-jobs/catalog/{job_id}/runs/{workspace_id}/uploads/raw_data"

    assert client.post(f"{base}?filename=big.csv&offset=0", content=b"AAAA").status_code == 201
    second = client.post(f"{base}?filename=big.csv&offset=4", content=b"BBBB")
    assert second.status_code == 201
    assert second.json()["size"] == 8
    assembled = runtime.run_workspaces.input_abspath(workspace_id, second.json()["handle"]).read_bytes()
    assert assembled == b"AAAABBBB"

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_directory_upload_resolves_to_input_dir(tmp_path: Path):
    client = _client(tmp_path)
    runtime = app.dependency_overrides[get_runtime]()
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    field = _io_field(
        "folder",
        "Folder",
        {"target": "stage_input_source", "stage": "run", "input": "folder"},
        io_role="input",
        field_type="directory",
        sources=["upload"],
    )
    field["accept"] = "directory"
    job_id = client.post(
        "/api/v1/published-jobs/admin",
        json={"name": "Folder demo", "definition_content": JOB_DEF_UPLOAD, "status": "published", "fields": [field]},
    ).json()["id"]
    workspace_id = client.post(f"/api/v1/published-jobs/catalog/{job_id}/runs/draft").json()["workspace_id"]
    base = f"/api/v1/published-jobs/catalog/{job_id}/runs/{workspace_id}/uploads/folder"
    assert client.post(f"{base}?filename=a.csv&relpath=sub/a.csv", content=b"a").status_code == 201
    assert client.post(f"{base}?filename=b.csv&relpath=b.csv", content=b"b").status_code == 201

    run = client.post(
        f"/api/v1/published-jobs/catalog/{job_id}/runs",
        json={"values": {"folder": ""}, "workspace_id": workspace_id, "file_bindings": {"folder": {"kind": "upload", "path": ""}}},
    )
    assert run.status_code == 201
    folder_source = run.json()["group"]["tasks"][0]["input_sources"]["folder"].replace("\\", "/")
    assert folder_source.endswith("inputs/folder")
    uploaded = runtime.run_workspaces.input_dir(workspace_id, "folder")
    assert (uploaded / "sub" / "a.csv").read_text(encoding="utf-8") == "a"
    assert (uploaded / "b.csv").read_text(encoding="utf-8") == "b"

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_admin_lists_roots_and_rewind_rejects_workspace_run(tmp_path: Path):
    (tmp_path / "share").mkdir()
    client = _client(tmp_path, shared_roots=[{"id": "ecoli", "label": "E. coli data", "path": str(tmp_path / "share")}])
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})

    roots = client.get("/api/v1/published-jobs/admin/shared-roots")
    assert roots.status_code == 200
    assert {"id": "ecoli", "label": "E. coli data"} in roots.json()

    field = _io_field(
        "raw_data",
        "Raw",
        {"target": "stage_input_source", "stage": "run", "input": "raw_data"},
        io_role="input",
        field_type="file",
        sources=["upload"],
    )
    job_id = client.post(
        "/api/v1/published-jobs/admin",
        json={"name": "Rewind demo", "definition_content": JOB_DEF_UPLOAD, "status": "published", "fields": [field]},
    ).json()["id"]
    workspace_id = client.post(f"/api/v1/published-jobs/catalog/{job_id}/runs/draft").json()["workspace_id"]
    client.post(
        f"/api/v1/published-jobs/catalog/{job_id}/runs/{workspace_id}/uploads/raw_data?filename=in.csv",
        content=b"x",
    )
    run_id = client.post(
        f"/api/v1/published-jobs/catalog/{job_id}/runs",
        json={"values": {"raw_data": ""}, "workspace_id": workspace_id, "file_bindings": {"raw_data": {"kind": "upload", "path": "inputs/raw_data/in.csv"}}},
    ).json()["id"]

    rewind = client.post(f"/api/v1/published-jobs/my-runs/{run_id}/rewind")
    assert rewind.status_code == 400

    app.dependency_overrides.clear()
    get_runtime.cache_clear()


def test_user_deletes_own_run_and_workspace(tmp_path: Path):
    client = _client(tmp_path)
    runtime = app.dependency_overrides[get_runtime]()
    client.post("/api/v1/pipeline-yamls", json={"name": "demo.yaml", "content": PIPELINE_YAML, "overwrite": True})
    field = _io_field(
        "raw_data",
        "Raw",
        {"target": "stage_input_source", "stage": "run", "input": "raw_data"},
        io_role="input",
        field_type="file",
        sources=["upload"],
    )
    job_id = client.post(
        "/api/v1/published-jobs/admin",
        json={"name": "Delete demo", "definition_content": JOB_DEF_UPLOAD, "status": "published", "fields": [field]},
    ).json()["id"]
    workspace_id = client.post(f"/api/v1/published-jobs/catalog/{job_id}/runs/draft").json()["workspace_id"]
    client.post(f"/api/v1/published-jobs/catalog/{job_id}/runs/{workspace_id}/uploads/raw_data?filename=in.csv", content=b"x")
    run_id = client.post(
        f"/api/v1/published-jobs/catalog/{job_id}/runs",
        json={"values": {"raw_data": ""}, "workspace_id": workspace_id, "file_bindings": {"raw_data": {"kind": "upload", "path": "inputs/raw_data/in.csv"}}},
    ).json()["id"]
    assert runtime.run_workspaces.exists(workspace_id)

    deleted = client.delete(f"/api/v1/published-jobs/my-runs/{run_id}")
    assert deleted.status_code == 204
    assert all(run["id"] != run_id for run in client.get("/api/v1/published-jobs/my-runs").json())
    assert client.get(f"/api/v1/published-jobs/my-runs/{run_id}").status_code == 404
    assert not runtime.run_workspaces.exists(workspace_id)

    app.dependency_overrides.clear()
    get_runtime.cache_clear()
