from __future__ import annotations

from bio_pipeline_manager.published_jobs import _apply_binding


def test_stage_input_source_coerces_non_string_value():
    # A numeric field mistakenly bound to stage_input_source must not produce a
    # non-string in input_sources (which would crash job serialization later).
    data = {"stages": [{"name": "run"}]}
    _apply_binding(
        data,
        {"target": "stage_input_source", "stage": "run", "input": "start"},
        10,
    )
    assert data["stages"][0]["input_sources"]["start"] == "10"
    assert isinstance(data["stages"][0]["input_sources"]["start"], str)


def test_stage_process_arg_preserves_numeric_value():
    # The correct target for scalars keeps the native type.
    data = {"stages": [{"name": "run"}]}
    _apply_binding(
        data,
        {
            "target": "stage_process_arg",
            "stage": "run",
            "process": "generated_numbers",
            "parameter": "start",
        },
        10,
    )
    assert data["stages"][0]["process_arg_mapping"]["generated_numbers"]["start"] == 10
