import pytest

from bio_pipeline_manager.type_library_store import TypeLibraryStore
from bio_pipeline_manager.type_schema import TypeSchemaError

RULE = {
    "description": "rule",
    "fields": {
        "direction": {"type": "enum", "options": ["alphabetical", "numerical"], "required": False},
        "sample_size": {"type": "integer", "required": False},
    },
}


def test_upsert_get_and_persist(tmp_path):
    store = TypeLibraryStore(tmp_path / "type_library.yaml")
    store.upsert("CustomReplicateRule", RULE)

    assert "CustomReplicateRule" in store.all()
    assert store.get("CustomReplicateRule")["fields"]["sample_size"]["type"] == "integer"

    # A fresh store over the same file sees the persisted type.
    reopened = TypeLibraryStore(tmp_path / "type_library.yaml")
    assert "CustomReplicateRule" in reopened.all()


def test_upsert_rejects_invalid_name(tmp_path):
    store = TypeLibraryStore(tmp_path / "type_library.yaml")
    with pytest.raises(TypeSchemaError, match="Type name"):
        store.upsert("123 bad", RULE)


def test_upsert_validates_whole_library(tmp_path):
    store = TypeLibraryStore(tmp_path / "type_library.yaml")
    with pytest.raises(TypeSchemaError, match="unknown type"):
        store.upsert("Policy", {"fields": {"rule": {"type": "DoesNotExist"}}})


def test_delete_rejects_when_it_would_strand_a_reference(tmp_path):
    store = TypeLibraryStore(tmp_path / "type_library.yaml")
    store.upsert("CustomReplicateRule", RULE)
    store.upsert("Policy", {"fields": {"rule": {"type": "CustomReplicateRule"}}})
    with pytest.raises(TypeSchemaError):
        store.delete("CustomReplicateRule")  # Policy still references it
    # The dependent type can be removed first, then the base type.
    store.delete("Policy")
    store.delete("CustomReplicateRule")
    assert store.all() == {}


def test_upsert_simple_scalar_type(tmp_path):
    store = TypeLibraryStore(tmp_path / "type_library.yaml")
    store.upsert("SampleId", {"description": "an id", "type": "string"})
    store.upsert("Direction", {"type": "enum", "options": ["up", "down"], "default": "up"})

    stored = store.get("SampleId")
    assert stored["type"] == "string"
    assert "fields" not in stored

    direction = store.get("Direction")
    assert direction["type"] == "enum"
    assert direction["options"] == ["up", "down"]
    assert direction["default"] == "up"

    # Persists across a reopen.
    reopened = TypeLibraryStore(tmp_path / "type_library.yaml")
    assert reopened.get("SampleId")["type"] == "string"


def test_upsert_simple_type_rejects_non_primitive(tmp_path):
    store = TypeLibraryStore(tmp_path / "type_library.yaml")
    with pytest.raises(TypeSchemaError, match="must be a primitive"):
        store.upsert("Bad", {"type": "NotAPrimitive"})


def test_compound_field_can_reference_a_simple_type(tmp_path):
    store = TypeLibraryStore(tmp_path / "type_library.yaml")
    store.upsert("SampleId", {"type": "string"})
    store.upsert("Policy", {"fields": {"ids": {"type": "SampleId", "container": "list"}}})
    assert "Policy" in store.all()


def test_upsert_persists_source_and_preserves_on_edit(tmp_path):
    store = TypeLibraryStore(tmp_path / "type_library.yaml")
    store.upsert("CustomReplicateRule", {**RULE, "source": "labUtils.media_bot.CustomReplicateRule"})
    assert store.get("CustomReplicateRule")["source"] == "labUtils.media_bot.CustomReplicateRule"

    # The edit form re-saves fields without resending source — the origin survives.
    store.upsert("CustomReplicateRule", RULE)
    assert store.get("CustomReplicateRule")["source"] == "labUtils.media_bot.CustomReplicateRule"


def test_get_missing_raises_keyerror(tmp_path):
    store = TypeLibraryStore(tmp_path / "type_library.yaml")
    with pytest.raises(KeyError):
        store.get("Nope")
