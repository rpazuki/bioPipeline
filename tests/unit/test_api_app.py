"""Tests for the lightweight notebook-facing FastAPI server (api/app.py)."""

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from bio_pipeline_manager.api.app import create_app  # noqa: E402


VALID_YAML = """
pipelines:
  - demo:
      Inputs: []
      Processes: []
      Outputs: []
"""

DEFINITION = """
job: nb_demo
variables: {tag: [T1, T2]}
stages:
  - name: only
    pipeline_yaml: demo.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out/{tag}
"""


def test_preview_and_submit_job_definition(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    client.post("/yamls", json={"name": "demo.yaml", "content": VALID_YAML, "overwrite": True})

    preview = client.post("/job-definitions/preview", json={"content": DEFINITION})
    assert preview.status_code == 200
    assert preview.json()["task_count"] == 2
    assert preview.json()["job_name"] == "nb_demo"

    submit = client.post("/job-definitions", json={"content": DEFINITION})
    assert submit.status_code == 200
    parent_id = submit.json()["parent_job_id"]
    assert submit.json()["total"] == 2

    listing = client.get("/job-definitions")
    assert any(g["parent_job_id"] == parent_id for g in listing.json())

    detail = client.get(f"/job-definitions/{parent_id}")
    assert detail.status_code == 200
    assert detail.json()["total"] == 2

    assert client.get("/job-definitions/nope").status_code == 404


def test_preview_invalid_returns_400(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    assert client.post("/job-definitions/preview", json={"content": "job: x\n"}).status_code == 400
