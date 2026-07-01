"""End-to-end: a typed published field renders into a native structure in the YAML."""

import textwrap

import pytest
import yaml

from bio_pipeline_manager.job_definition import expand
from bio_pipeline_manager.models import utc_now
from bio_pipeline_manager.published_jobs import (
    PublishedJobError,
    PublishedJobRecord,
    PublishedJobStore,
    refresh_typed_field_schemas,
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


def _plain_field(*, nullable: bool) -> dict:
    return {
        "id": "threshold",
        "label": "Threshold",
        "type": "string",
        "required": False,
        "nullable": nullable,
        "default": "",
        "bindings": [
            {
                "target": "stage_process_arg",
                "stage": "s1",
                "process": "df_stats",
                "parameter": "threshold",
            }
        ],
    }


def _record_with_definition(definition: str, field: dict) -> PublishedJobRecord:
    now = utc_now()
    return PublishedJobRecord(
        id="job1",
        name="demo",
        description="",
        status="published",
        version=1,
        definition_name="demo.yaml",
        definition_content=definition,
        fields=[field],
        created_at=now,
        updated_at=now,
        published_at=now,
        created_by="admin",
        updated_by="admin",
    )


def test_output_field_template_tokens_are_rendered_not_escaped():
    # Regression: an io_role:output field carries a re-rooted template with live tokens
    # (e.g. <ws>/processed/{variant.name}). Brace escaping must NOT touch it, so the
    # token still resolves to the matrix variant at materialization instead of leaving a
    # folder literally named "{variant.name}".
    definition = textwrap.dedent(
        """
        job: demo
        variables:
          variant:
            - {name: replicate, pipeline: p}
        stages:
          - name: s1
            pipeline: "{variant.pipeline}"
            pipeline_yaml: x.yaml
            output_dir: placeholder
        """
    ).strip()
    field = {
        "id": "out",
        "label": "Output",
        "type": "directory",
        "io_role": "output",
        "bindings": [{"target": "definition_path", "path": ["stages", "s1", "output_dir"]}],
    }
    record = _record_with_definition(definition, field)
    rendered = render_definition(record, {"out": "/ws/processed/{variant.name}"})
    assert "{{variant.name}}" not in rendered  # not escaped
    tasks = expand(rendered, lenient=True)
    assert tasks[0].output_dir == "/ws/processed/replicate"


def _scalar_single_field() -> dict:
    library = {"Pattern": {"type": "string"}}
    return {
        "id": "name_pattern",
        "label": "Name pattern",
        "type": "typed",
        "schema_ref": "Pattern",
        "container": "single",
        "type_schema": resolve_type(library, "Pattern"),
        "bindings": [
            {"target": "stage_process_arg", "stage": "s1", "process": "df_proc", "parameter": "pattern"}
        ],
    }


def test_scalar_single_string_value_is_not_yaml_parsed():
    # A simple (scalar) string type submits a bare value; a regex like this looks like a
    # YAML flow sequence and must NOT be parsed (previously crashed with a 500).
    record = _record(_scalar_single_field())
    pattern = "[A-Za-z0-9]+_[A-Za-z0-9]+"
    rendered = yaml.safe_load(render_definition(record, {"name_pattern": pattern}))
    assert rendered["stages"][0]["process_arg_mapping"]["df_proc"]["pattern"] == pattern


def test_scalar_value_with_braces_survives_template_rendering():
    # A literal value with braces ({id}, \d{2}) must reach the function as-is, not be
    # read as a {token} by the job-definition renderer. render_definition escapes the
    # braces; expand()'s renderer restores them.
    record = _record(_scalar_single_field())
    value = r"sample_{id}_\d{2}"
    rendered = render_definition(record, {"name_pattern": value})
    assert "{{" in rendered  # stored escaped
    tasks = expand(rendered, lenient=True)
    assert tasks[0].process_arg_mapping["df_proc"]["pattern"] == value


def test_scalar_list_values_with_braces_survive():
    library = {"Pattern": {"type": "string"}}
    field = {
        "id": "patterns",
        "label": "Patterns",
        "type": "typed",
        "schema_ref": "Pattern",
        "container": "list",
        "type_schema": resolve_type(library, "Pattern"),
        "bindings": [
            {"target": "stage_process_arg", "stage": "s1", "process": "df_proc", "parameter": "patterns"}
        ],
    }
    record = _record(field)
    rendered = render_definition(record, {"patterns": [r"\d{2}", "a{b}c"]})
    tasks = expand(rendered, lenient=True)
    assert tasks[0].process_arg_mapping["df_proc"]["patterns"] == [r"\d{2}", "a{b}c"]


def _builtin_scalar_field(container: str, leaf: str) -> dict:
    """A field bound to an inline built-in collection (no library ref) — the shape the
    admin UI's built-in 'Structured type' options (List/Map of text/number) produce."""
    return {
        "id": "items",
        "label": "Items",
        "type": "typed",
        "schema_ref": "",
        "container": container,
        "type_schema": {
            "name": f"{container} of {leaf}",
            "kind": "scalar",
            "scalar": {"type": leaf, "options": [], "help": "", "example": ""},
        },
        "bindings": [
            {"target": "stage_process_arg", "stage": "s1", "process": "df_proc", "parameter": "items"}
        ],
    }


def test_inline_builtin_scalar_list_passes_through_and_coerces():
    # A built-in "List of whole numbers": resolve_typed_fields keeps the inline schema
    # verbatim (no library lookup), and render coerces each entry to an int.
    field = _builtin_scalar_field("list", "integer")
    [resolved] = resolve_typed_fields([field], {})
    assert resolved is field  # inline typed field is passed through untouched
    record = _record(field)
    rendered = yaml.safe_load(render_definition(record, {"items": ["1", "2", 3]}))
    assert rendered["stages"][0]["process_arg_mapping"]["df_proc"]["items"] == [1, 2, 3]


def test_inline_builtin_scalar_map_coerces_entries():
    field = _builtin_scalar_field("map", "float")
    record = _record(field)
    rendered = yaml.safe_load(render_definition(record, {"items": {"a": "1.5", "b": 2}}))
    assert rendered["stages"][0]["process_arg_mapping"]["df_proc"]["items"] == {"a": 1.5, "b": 2.0}


def test_inline_builtin_typed_field_needs_no_library():
    # The embedded schema means an inline collection resolves against an empty library —
    # the feature works with no admin-defined named type at all.
    field = _builtin_scalar_field("list", "string")
    [resolved] = resolve_typed_fields([field], {})
    assert resolved["type_schema"]["kind"] == "scalar"


def test_invalid_structured_value_raises_published_error_not_500():
    field = {
        "id": "cfg",
        "label": "Config",
        "type": "object",
        "bindings": [{"target": "stage_process_arg", "stage": "s1", "process": "df", "parameter": "cfg"}],
    }
    record = _record(field)
    with pytest.raises(PublishedJobError, match="not valid JSON/YAML"):
        render_definition(record, {"cfg": "[A-Za-z0-9]+_oops"})


def test_nullable_field_empty_value_renders_as_none():
    record = _record(_plain_field(nullable=True))
    rendered = yaml.safe_load(render_definition(record, {"threshold": ""}))
    assert rendered["stages"][0]["process_arg_mapping"]["df_stats"]["threshold"] is None


def test_non_nullable_empty_optional_field_keeps_empty_string():
    record = _record(_plain_field(nullable=False))
    rendered = yaml.safe_load(render_definition(record, {"threshold": ""}))
    assert rendered["stages"][0]["process_arg_mapping"]["df_stats"]["threshold"] == ""


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


# A library where the inner field is *required* — the stale state a job is published with
# before an admin later marks the field optional in the library.
REQUIRED_LIBRARY = {
    "CustomReplicateRule": {
        "fields": {
            "direction": {"type": "enum", "options": ["alphabetical", "numerical"], "required": False},
            "sample_size": {"type": "integer", "required": True},
        }
    }
}


def _sample_size_required(record: PublishedJobRecord) -> bool:
    [field] = [f for f in record.fields if f.get("schema_ref") == "CustomReplicateRule"]
    [inner] = [n for n in field["type_schema"]["fields"] if n["name"] == "sample_size"]
    return inner["required"]


def test_refresh_typed_field_schemas_picks_up_library_edit(tmp_path):
    store = PublishedJobStore(tmp_path / "state.sqlite")
    # Publish a job whose frozen schema is resolved against the *required* library.
    [stale_field] = resolve_typed_fields([_typed_map_field()], REQUIRED_LIBRARY)
    typed = store.create(
        name="typed_demo",
        description="",
        definition_name="typed_demo.yaml",
        definition_content=DEFINITION,
        fields=[stale_field],
        actor="admin",
        status="published",
    )
    # A second job that doesn't reference the type must be left completely alone.
    plain = store.create(
        name="plain_demo",
        description="",
        definition_name="plain_demo.yaml",
        definition_content=DEFINITION,
        fields=[_plain_field(nullable=False)],
        actor="admin",
        status="published",
    )
    assert _sample_size_required(store.get(typed.id)) is True

    # The admin edits the library to make sample_size optional (LIBRARY has required=False).
    updated = refresh_typed_field_schemas(store, LIBRARY, actor="editor")

    assert updated == [typed.id]
    refreshed = store.get(typed.id)
    assert _sample_size_required(refreshed) is False
    assert refreshed.version == typed.version + 1
    assert refreshed.updated_by == "editor"
    # The unrelated job is untouched: no version bump, no re-attribution.
    assert store.get(plain.id).version == plain.version
    assert store.get(plain.id).updated_by == "admin"


def test_refresh_typed_field_schemas_is_idempotent(tmp_path):
    store = PublishedJobStore(tmp_path / "state.sqlite")
    [field] = resolve_typed_fields([_typed_map_field()], LIBRARY)
    job = store.create(
        name="typed_demo",
        description="",
        definition_name="typed_demo.yaml",
        definition_content=DEFINITION,
        fields=[field],
        actor="admin",
        status="published",
    )
    # Already in step with the library — a refresh changes nothing and bumps no versions.
    assert refresh_typed_field_schemas(store, LIBRARY, actor="editor") == []
    assert store.get(job.id).version == job.version


def test_refresh_typed_field_schemas_skips_unresolvable_jobs(tmp_path):
    store = PublishedJobStore(tmp_path / "state.sqlite")
    [field] = resolve_typed_fields([_typed_map_field()], LIBRARY)
    job = store.create(
        name="typed_demo",
        description="",
        definition_name="typed_demo.yaml",
        definition_content=DEFINITION,
        fields=[field],
        actor="admin",
        status="published",
    )
    # The referenced type is gone from the library: the job keeps its last-known schema
    # rather than being corrupted, and is not reported as updated.
    assert refresh_typed_field_schemas(store, {}, actor="editor") == []
    assert _sample_size_required(store.get(job.id)) is False
    assert store.get(job.id).version == job.version
