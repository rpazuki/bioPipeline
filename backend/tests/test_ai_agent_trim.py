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


def test_get_pipeline_content_is_capped():
    out = _model_tool_result("get_pipeline_yaml", {"name": "x.yaml", "content": "y" * 99999})
    assert "truncated" in out or len(out["content"]) < 99999


def test_oversized_result_is_truncated():
    out = _model_tool_result("unknown_tool", {"blob": "z" * (_MAX_TOOL_RESULT_CHARS * 2)})
    assert out.get("truncated") is True
