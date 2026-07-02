import sqlite3

import pytest

from bio_pipeline_manager.typed_value_store import SavedTypedValueStore

# Legacy (pre-named-case) schema: a single value per (user, type_key, container).
_LEGACY_DDL = """
CREATE TABLE saved_typed_values (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    type_key TEXT NOT NULL,
    container TEXT NOT NULL DEFAULT 'single',
    label TEXT NOT NULL DEFAULT '',
    type_schema TEXT NOT NULL DEFAULT '{}',
    value_kind TEXT NOT NULL DEFAULT 'typed',
    field_schema TEXT NOT NULL DEFAULT '{}',
    field_value TEXT NOT NULL DEFAULT 'null',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, type_key, container)
)
"""


def _store(tmp_path) -> SavedTypedValueStore:
    return SavedTypedValueStore(tmp_path / "state.sqlite")


def _save(store, name="", **overrides):
    kwargs = dict(user_id="u1", type_key="Rule", container="single", label="Rule", type_schema={}, value=1)
    kwargs.update(overrides)
    return store.upsert(name=name, **kwargs)


def test_single_instance_upsert_overwrites_one_default(tmp_path):
    store = _store(tmp_path)
    first = _save(store, value={"x": 1})
    assert first.name == ""
    assert first.is_default is True
    # Re-saving the same (type, container, name="") overwrites in place.
    again = _save(store, value={"x": 2})
    assert again.id == first.id
    assert again.value == {"x": 2}
    assert len(store.list_cases("u1", "Rule", "single")) == 1


def test_multiple_named_cases_first_is_default(tmp_path):
    store = _store(tmp_path)
    slab = _save(store, name="SLAB", value={"x": 1})
    wt = _save(store, name="WT", value={"x": 2})
    assert slab.is_default is True  # first case becomes the group's default
    assert wt.is_default is False
    assert [case.name for case in store.list_cases("u1", "Rule", "single")] == ["SLAB", "WT"]
    assert store.get_default("u1", "Rule", "single").id == slab.id


def test_set_default_moves_flag(tmp_path):
    store = _store(tmp_path)
    slab = _save(store, name="SLAB")
    wt = _save(store, name="WT")
    store.set_default(wt.id)
    assert store.get_default("u1", "Rule", "single").id == wt.id
    assert store.get_by_key("u1", "Rule", "single", "SLAB").is_default is False
    assert store.get_by_key("u1", "Rule", "single", "WT").is_default is True
    assert slab.id != wt.id


def test_make_default_via_upsert_clears_siblings(tmp_path):
    store = _store(tmp_path)
    _save(store, name="A")
    b = _save(store, name="B", make_default=True)
    assert store.get_by_key("u1", "Rule", "single", "A").is_default is False
    assert store.get_default("u1", "Rule", "single").id == b.id


def test_delete_default_promotes_sibling(tmp_path):
    store = _store(tmp_path)
    a = _save(store, name="A")
    b = _save(store, name="B")
    assert a.is_default is True
    store.delete(a.id)
    remaining = store.list_cases("u1", "Rule", "single")
    assert [case.id for case in remaining] == [b.id]
    assert remaining[0].is_default is True  # the sole survivor is promoted


def test_update_rename_and_conflict(tmp_path):
    store = _store(tmp_path)
    _save(store, name="A")
    b = _save(store, name="B")
    renamed = store.update(b.id, name="B2")
    assert renamed.name == "B2"
    with pytest.raises(ValueError, match="already exists"):
        store.update(renamed.id, name="A")


def test_migrates_legacy_three_column_table(tmp_path):
    db = tmp_path / "state.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(_LEGACY_DDL)
    conn.execute(
        "INSERT INTO saved_typed_values "
        "(id, user_id, type_key, container, label, type_schema, value_kind, field_schema, field_value, created_at, updated_at) "
        "VALUES ('r1','u1','Rule','single','Rule','{}','typed','{}','5','2020-01-01T00:00:00+00:00','2020-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    store = SavedTypedValueStore(db)  # __init__ -> init() runs the migration
    legacy = store.get("r1")
    assert legacy.name == ""
    assert legacy.is_default is True  # promoted to its group's default
    assert legacy.value == 5

    # The old UNIQUE(user, type, container) is relaxed, so a second named case fits.
    second = _save(store, name="Second", value=6)
    assert second.id != "r1"
    assert len(store.list_cases("u1", "Rule", "single")) == 2
