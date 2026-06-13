import pytest

from bio_pipeline_manager.type_schema import (
    TypeSchemaError,
    coerce_typed_value,
    resolve_type,
    suggest_type,
    validate_library,
)

CUSTOM_RULE_LIB = {
    "CustomReplicateRule": {
        "description": "One strain's replicate-aggregation rule",
        "fields": {
            "direction": {"type": "enum", "options": ["alphabetical", "numerical"], "required": False},
            "pattern": {"type": "string", "required": False},
            "sample_size": {"type": "integer", "required": False},
        },
    }
}


# --- validation ---------------------------------------------------------- #
def test_validate_accepts_leaf_and_nested_types():
    library = {
        **CUSTOM_RULE_LIB,
        "Policy": {"fields": {"rule": {"type": "CustomReplicateRule"}, "tags": {"type": "string", "container": "list"}}},
    }
    validate_library(library)  # does not raise


def test_validate_rejects_unknown_reference():
    with pytest.raises(TypeSchemaError, match="unknown type 'Nope'"):
        validate_library({"T": {"fields": {"x": {"type": "Nope"}}}})


def test_validate_rejects_bad_container():
    with pytest.raises(TypeSchemaError, match="invalid container"):
        validate_library({"T": {"fields": {"x": {"type": "string", "container": "set"}}}})


def test_validate_rejects_enum_without_options():
    with pytest.raises(TypeSchemaError, match="enum but lists no 'options'"):
        validate_library({"T": {"fields": {"x": {"type": "enum"}}}})


def test_validate_rejects_cycle():
    library = {
        "A": {"fields": {"b": {"type": "B"}}},
        "B": {"fields": {"a": {"type": "A"}}},
    }
    with pytest.raises(TypeSchemaError, match="cycle"):
        validate_library(library)


def test_validate_requires_non_empty_fields():
    with pytest.raises(TypeSchemaError, match="non-empty 'fields'"):
        validate_library({"T": {"fields": {}}})


# --- resolution ---------------------------------------------------------- #
def test_resolve_flattens_leaf_fields():
    schema = resolve_type(CUSTOM_RULE_LIB, "CustomReplicateRule")
    assert schema["name"] == "CustomReplicateRule"
    by_name = {f["name"]: f for f in schema["fields"]}
    assert by_name["direction"]["type"] == "enum"
    assert by_name["direction"]["options"] == [
        {"label": "alphabetical", "value": "alphabetical"},
        {"label": "numerical", "value": "numerical"},
    ]
    assert by_name["sample_size"]["type"] == "integer"
    assert by_name["sample_size"]["required"] is False


def test_resolve_nested_type_inlines_schema():
    library = {**CUSTOM_RULE_LIB, "Policy": {"fields": {"rule": {"type": "CustomReplicateRule"}}}}
    schema = resolve_type(library, "Policy")
    rule = schema["fields"][0]
    assert rule["type"] == "typed"
    assert rule["schema_ref"] == "CustomReplicateRule"
    assert {f["name"] for f in rule["type_schema"]["fields"]} == {"direction", "pattern", "sample_size"}


# --- coercion ------------------------------------------------------------ #
def _map_field():
    return {
        "type": "typed",
        "container": "map",
        "label": "custom_rules",
        "type_schema": resolve_type(CUSTOM_RULE_LIB, "CustomReplicateRule"),
    }


def test_coerce_map_of_type_produces_native_dict():
    field = _map_field()
    value = {
        "SLAB": {"direction": "alphabetical", "sample_size": "3"},
        "WT": {"direction": "alphabetical", "sample_size": 2},
    }
    coerced = coerce_typed_value(field, value)
    assert coerced == {
        "SLAB": {"direction": "alphabetical", "sample_size": 3},  # string coerced to int
        "WT": {"direction": "alphabetical", "sample_size": 2},
    }


def test_coerce_rejects_unknown_field():
    field = _map_field()
    with pytest.raises(TypeSchemaError, match="unknown field"):
        coerce_typed_value(field, {"SLAB": {"directon": "alphabetical"}})


def test_coerce_rejects_invalid_enum():
    field = _map_field()
    with pytest.raises(TypeSchemaError, match="must be one of"):
        coerce_typed_value(field, {"SLAB": {"direction": "sideways"}})


def test_coerce_single_requires_required_field():
    library = {"Threshold": {"fields": {"metric": {"type": "string"}, "cutoff": {"type": "float"}}}}
    field = {"type": "typed", "container": "single", "type_schema": resolve_type(library, "Threshold")}
    with pytest.raises(TypeSchemaError, match="required"):
        coerce_typed_value(field, {"metric": "od600"})  # cutoff missing


def test_coerce_list_of_type():
    library = {"Threshold": {"fields": {"cutoff": {"type": "float", "required": False}}}}
    field = {"type": "typed", "container": "list", "type_schema": resolve_type(library, "Threshold")}
    assert coerce_typed_value(field, [{"cutoff": "0.5"}, {"cutoff": 1}]) == [{"cutoff": 0.5}, {"cutoff": 1.0}]


# --- suggestion ---------------------------------------------------------- #
def test_suggest_map_of_type():
    value = {"SLAB": {"direction": "alphabetical", "sample_size": 3}}
    assert suggest_type(CUSTOM_RULE_LIB, value) == ("CustomReplicateRule", "map")


def test_suggest_returns_none_when_no_match():
    assert suggest_type(CUSTOM_RULE_LIB, {"a": {"totally": "different"}}) is None
