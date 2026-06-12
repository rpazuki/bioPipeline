from __future__ import annotations

from datetime import datetime

import pytest

from bio_pipeline_manager.job_definition import expand
from bio_pipeline_manager.published_jobs import (
    PublishedJobError,
    PublishedJobRecord,
    _apply_binding,
    _coerce_values,
    _provided_later_locations,
    _reconcile_variable_value,
    render_definition,
)


def _record(definition_content: str, fields: list[dict]) -> PublishedJobRecord:
    now = datetime.now()
    return PublishedJobRecord(
        id="x", name="n", description="", status="published", version=1,
        definition_name="d", definition_content=definition_content, fields=fields,
        created_at=now, updated_at=now, published_at=now, created_by="a", updated_by="a",
    )


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


def test_coerce_values_treats_unfilled_placeholder_as_missing():
    # A field whose value is still the $WILL_PROVIDE$ placeholder (the researcher
    # didn't override the definition's placeholder default) reports clearly rather
    # than letting the placeholder reach the queue.
    fields = [{"id": "mapping", "label": "Mapping file", "type": "string", "required": True, "default": "$WILL_PROVIDE$"}]
    with pytest.raises(PublishedJobError, match="Mapping file"):
        _coerce_values(fields, {})


def test_coerce_values_placeholder_required_even_when_field_not_required():
    # A placeholder always needs a value, even on an explicitly non-required field.
    fields = [{"id": "mapping", "label": "Mapping file", "type": "string", "required": False, "default": "$WILL_PROVIDE$"}]
    with pytest.raises(PublishedJobError, match="must be provided"):
        _coerce_values(fields, {})


def test_coerce_values_accepts_overridden_placeholder():
    fields = [{"id": "mapping", "label": "Mapping file", "type": "string", "required": True, "default": "$WILL_PROVIDE$"}]
    assert _coerce_values(fields, {"mapping": "/data/real_mapping.yaml"}) == {"mapping": "/data/real_mapping.yaml"}


def test_provided_later_locations_lists_remaining_paths():
    data = {"defaults": {"data_root": "$WILL_PROVIDE$", "ok": "/real"}, "stages": [{"output_dir": "$WILL_PROVIDE$"}]}
    assert _provided_later_locations(data) == ["defaults.data_root", "stages[0].output_dir"]


_DEF = """job: demo
defaults:
  data_root: $WILL_PROVIDE$
  mapping: $WILL_PROVIDE$
stages:
  - name: fit
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: mapping_file, mapping: "{mapping}"}
    output_dir: "{data_root}/out/{item.stem}"
    input_sources: {raw: "{data_root}/{item.raw}"}
"""

_FIELD_ROOT = {"id": "default_data_root", "label": "Data root", "type": "string", "required": True,
               "default": "$WILL_PROVIDE$", "bindings": [{"target": "definition_path", "path": ["defaults", "data_root"]}]}
_FIELD_MAP = {"id": "default_mapping", "label": "Mapping", "type": "string", "required": True,
              "default": "$WILL_PROVIDE$", "bindings": [{"target": "definition_path", "path": ["defaults", "mapping"]}]}


def test_render_definition_succeeds_when_all_placeholders_provided():
    record = _record(_DEF, [_FIELD_ROOT, _FIELD_MAP])
    rendered = render_definition(record, {"default_data_root": "/real/root", "default_mapping": "/real/map.yaml"})
    assert "$WILL_PROVIDE$" not in rendered


def test_render_definition_rejects_unexposed_placeholder():
    # Only the mapping is exposed; data_root keeps its placeholder. The researcher
    # path must fail with an actionable message — never the direct-submit guard.
    record = _record(_DEF, [_FIELD_MAP])
    with pytest.raises(PublishedJobError, match=r"defaults\.data_root"):
        render_definition(record, {"default_mapping": "/real/map.yaml"})


_VAR_DEF = """job: demo
variables:
  variant:
    - {name: a, group_cols: well, pipeline: p_a}
    - {name: b, group_cols: gid, pipeline: p_b}
defaults:
  data_root: /data
stages:
  - name: s
    pipeline_yaml: p.yaml
    pipeline: "{variant.pipeline}"
    fanout: {type: none}
    output_dir: "/out/{variant.name}"
    process_arg_mapping:
      proc: {cols: "{variant.group_cols}"}
"""

# A variant option captured before the definition gained `group_cols` — the value
# is missing that field even though the current definition references it.
_STALE_VARIANT_FIELD = {
    "id": "var_variant", "label": "Variant", "type": "enum", "required": True,
    "default": {"name": "a", "pipeline": "p_a"},
    "options": [
        {"label": "a", "value": {"name": "a", "pipeline": "p_a"}},
        {"label": "b", "value": {"name": "b", "pipeline": "p_b"}},
    ],
    "bindings": [{"target": "definition_path", "path": ["variables", "variant"]}],
}


def test_reconcile_variable_value_fills_from_definition():
    original = {"variant": [{"name": "a", "group_cols": "well", "pipeline": "p_a"}]}
    binding = {"target": "definition_path", "path": ["variables", "variant"]}
    assert _reconcile_variable_value(original, binding, {"name": "a", "pipeline": "p_a"}) == {
        "name": "a", "group_cols": "well", "pipeline": "p_a",
    }


def test_reconcile_variable_value_ignores_non_variable_binding():
    binding = {"target": "stage_process_arg", "stage": "s", "process": "p", "parameter": "x"}
    assert _reconcile_variable_value({"variant": []}, binding, "v") == "v"


def test_render_definition_heals_stale_variant_option():
    # A researcher picking a stale option (missing group_cols) must still expand:
    # render reconciles the selection to the current definition entry by name.
    record = _record(_VAR_DEF, [_STALE_VARIANT_FIELD])
    tasks = expand(render_definition(record, {"var_variant": {"name": "b", "pipeline": "p_b"}}))
    assert len(tasks) == 1
    assert tasks[0].pipeline_name == "p_b"
    assert tasks[0].process_arg_mapping["proc"]["cols"] == "gid"
