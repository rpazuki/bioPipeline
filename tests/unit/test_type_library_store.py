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


def test_get_missing_raises_keyerror(tmp_path):
    store = TypeLibraryStore(tmp_path / "type_library.yaml")
    with pytest.raises(KeyError):
        store.get("Nope")
