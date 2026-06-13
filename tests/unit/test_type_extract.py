"""Introspection of Python classes into type-library entries."""

from __future__ import annotations

import dataclasses
from typing import Literal, Optional, TypedDict

import pytest
from pydantic import BaseModel

from bio_pipeline_manager.type_extract import TypeExtractError, extract_type
from bio_pipeline_manager.type_schema import validate_library


class CustomRule(TypedDict, total=False):
    """A strain's replicate rule."""

    direction: Literal["alphabetical", "numerical"]
    pattern: str
    sample_size: int


class Threshold(TypedDict):
    metric: str
    cutoff: float


class Policy(TypedDict):
    rule: CustomRule
    thresholds: list[Threshold]
    overrides: dict[str, CustomRule]
    note: Optional[str]


@dataclasses.dataclass
class Window:
    size: int
    label: str = "w"


class PydModel(BaseModel):
    name: str
    count: int = 3


def _qual(cls: type) -> str:
    return f"{__name__}.{cls.__name__}"


def test_extract_typeddict_total_false_optional_and_enum():
    result = extract_type(_qual(CustomRule))
    assert result["root"] == "CustomRule"
    fields = result["types"]["CustomRule"]["fields"]
    assert fields["direction"]["type"] == "enum"
    assert fields["direction"]["options"] == ["alphabetical", "numerical"]
    assert fields["sample_size"]["type"] == "integer"
    # total=False -> every field optional
    assert all(spec["required"] is False for spec in fields.values())
    assert result["types"]["CustomRule"]["description"] == "A strain's replicate rule."
    validate_library(result["types"])  # guaranteed loadable


def test_extract_nested_list_map_and_optional():
    result = extract_type(_qual(Policy))
    types = result["types"]
    # Root plus every referenced nested type is emitted.
    assert set(types) == {"Policy", "CustomRule", "Threshold"}
    policy = types["Policy"]["fields"]
    assert policy["rule"] == {"type": "CustomRule", "required": True}
    assert policy["thresholds"] == {"type": "Threshold", "container": "list", "required": True}
    assert policy["overrides"] == {"type": "CustomRule", "container": "map", "required": True}
    # Optional[str] -> string, required False
    assert policy["note"] == {"type": "string", "required": False}


def test_extract_dataclass_required_vs_default():
    fields = extract_type(_qual(Window))["types"]["Window"]["fields"]
    assert fields["size"] == {"type": "integer", "required": True}
    assert fields["label"]["required"] is False  # has a default


def test_extract_pydantic_required_vs_default():
    fields = extract_type(_qual(PydModel))["types"]["PydModel"]["fields"]
    assert fields["name"]["required"] is True
    assert fields["count"]["required"] is False


def test_extract_real_labutils_typeddict():
    result = extract_type("labUtils.media_bot.CustomReplicateRule")
    assert result["root"] == "CustomReplicateRule"
    assert set(result["types"]["CustomReplicateRule"]["fields"]) == {"direction", "pattern", "sample_size"}


def test_extract_rejects_non_structured():
    with pytest.raises(TypeExtractError, match="not a structured type"):
        extract_type("math.sqrt")


def test_extract_rejects_unresolvable():
    with pytest.raises(TypeExtractError):
        extract_type("nonexistent_module.Thing")
