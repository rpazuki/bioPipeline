import json

from bio_pipeline_manager.client import PipelineClient


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_client_posts_json(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.method
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse({"id": "job-1"})

    monkeypatch.setattr("bio_pipeline_manager.client.urlopen", fake_urlopen)

    result = PipelineClient("http://example.test").submit(
        "demo.yaml",
        "pipeline_1",
        "./outputs",
        input_sources={"raw": "raw.csv"},
        process_arg_mapping={"step": {"threshold": "0.5"}},
    )

    assert result == {"id": "job-1"}
    assert captured["url"] == "http://example.test/jobs"
    assert captured["method"] == "POST"
    assert captured["body"]["input_sources"] == {"raw": "raw.csv"}
    assert captured["body"]["process_arg_mapping"] == {"step": {"threshold": "0.5"}}
    assert captured["timeout"] == 30


def test_client_submit_definition_posts_to_job_definitions(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.method
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"parent_job_id": "grp-1", "total": 2})

    monkeypatch.setattr("bio_pipeline_manager.client.urlopen", fake_urlopen)

    result = PipelineClient("http://example.test").submit_definition("job: x\n")

    assert result == {"parent_job_id": "grp-1", "total": 2}
    assert captured["url"] == "http://example.test/job-definitions"
    assert captured["method"] == "POST"
    assert captured["body"]["content"] == "job: x\n"

