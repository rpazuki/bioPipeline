"""End-to-end: a typed published field renders into a native structure in the YAML."""

import textwrap

import pytest
import yaml

from bio_pipeline_manager.models import utc_now
from bio_pipeline_manager.published_jobs import (
    PublishedJobError,
    PublishedJobRecord,
    render_definition,
    resolve_typed_fields,
)
from bio_pipeline_manager.type_schema import resolve_type

LIBRARY = {
    "CustomReplicateRule": {
        "fields": {
            "direction": {"type": "enum", "options": ["alphabetical", "numerical"], "required": False},
            "sample_size": {"type": "integer", "required": False},
        }
    }
}

DEFINITION = textwrap.dedent(
    """
    job: typed_demo
    stages:
      - name: s1
        pipeline: p
        pipeline_yaml: x.yaml
        output_dir: out
    """
).strip()


def _record(field: dict) -> PublishedJobRecord:
    now = utc_now()
    return PublishedJobRecord(
        id="job1",
        name="typed_demo",
        description="",
        status="published",
        version=1,
        definition_name="typed_demo.yaml",
        definition_content=DEFINITION,
        fields=[field],
        created_at=now,
        updated_at=now,
        published_at=now,
        created_by="admin",
        updated_by="admin",
    )


def _typed_map_field() -> dict:
    return {
        "id": "custom_rules",
        "label": "Custom replicate rules",
        "type": "typed",
        "schema_ref": "CustomReplicateRule",
        "container": "map",
        "type_schema": resolve_type(LIBRARY, "CustomReplicateRule"),
        "bindings": [
            {
                "target": "stage_process_arg",
                "stage": "s1",
                "process": "df_replicate_stats",
                "parameter": "custom_rules",
            }
        ],
    }


def test_typed_map_renders_into_process_arg_mapping():
    record = _record(_typed_map_field())
    values = {
        "custom_rules": {
            "SLAB": {"direction": "alphabetical", "sample_size": "3"},
            "WT": {"direction": "alphabetical", "sample_size": 2},
        }
    }
    rendered = yaml.safe_load(render_definition(record, values))
    custom_rules = rendered["stages"][0]["process_arg_mapping"]["df_replicate_stats"]["custom_rules"]
    assert custom_rules == {
        "SLAB": {"direction": "alphabetical", "sample_size": 3},
        "WT": {"direction": "alphabetical", "sample_size": 2},
    }


def test_typed_field_invalid_value_raises_published_error():
    record = _record(_typed_map_field())
    with pytest.raises(PublishedJobError, match="must be one of|unknown field"):
        render_definition(record, {"custom_rules": {"SLAB": {"direction": "sideways"}}})


def test_resolve_typed_fields_denormalizes_schema_from_library():
    field = {
        "id": "custom_rules",
        "type": "typed",
        "schema_ref": "CustomReplicateRule",
        "container": "map",
        "bindings": [{"target": "stage_process_arg", "stage": "s1", "process": "p", "parameter": "custom_rules"}],
    }
    [resolved] = resolve_typed_fields([field], LIBRARY)
    assert resolved["type_schema"]["name"] == "CustomReplicateRule"
    assert resolved["container"] == "map"


def test_resolve_typed_fields_rejects_unknown_type():
    field = {"id": "x", "type": "typed", "schema_ref": "Ghost", "container": "single", "bindings": [{"target": "x"}]}
    with pytest.raises(PublishedJobError, match="Unknown type 'Ghost'"):
        resolve_typed_fields([field], LIBRARY)
