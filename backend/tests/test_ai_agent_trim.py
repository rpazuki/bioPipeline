from __future__ import annotations

from bio_pipeline_manager.ai_agent import _MAX_TOOL_RESULT_CHARS, _model_tool_result


def test_preview_result_drops_task_list():
    result = {"job_name": "j", "task_count": 50, "tasks": [{"i": i} for i in range(50)]}
    out = _model_tool_result("preview_job_definition", result)
    assert out["task_count"] == 50
    assert "tasks" not in out
    assert out["first_task"] == {"i": 0}


def test_save_pipeline_result_drops_content_echo():
    out = _model_tool_result(
        "save_pipeline_yaml",
        {"name": "x.yaml", "content": "BIG" * 5000, "pipelines": ["p"], "is_valid": True},
    )
    assert "content" not in out
    assert out == {"name": "x.yaml", "pipelines": ["p"], "is_valid": True, "error": None}


def test_get_pipeline_content_within_cap_survives_overall_ceiling():
    # A realistic file under the content cap must round-trip intact, not get
    # discarded by the overall result ceiling.
    content = "pipelines:\n" + "".join(f"  - p{i}: {{}}\n" for i in range(200))
    out = _model_tool_result("get_pipeline_yaml", {"name": "x.yaml", "content": content})
    assert out["content"] == content
    assert "truncated" not in out


def test_get_pipeline_content_is_line_truncated_when_huge():
    big = "\n".join(f"line {i}" for i in range(100_000))
    out = _model_tool_result("get_pipeline_yaml", {"name": "x.yaml", "content": big})
    # The content is preserved (capped) rather than replaced by a blind preview.
    assert "content" in out and "preview" not in out
    assert "# …[truncated" in out["content"]
    # The cut lands on a line boundary, so the partial YAML stays parseable.
    body = out["content"].split("\n# …[truncated")[0]
    assert big.startswith(body)
    assert big[len(body)] == "\n"


def test_oversized_result_is_truncated():
    out = _model_tool_result("unknown_tool", {"blob": "z" * (_MAX_TOOL_RESULT_CHARS * 2)})
    assert out.get("truncated") is True
