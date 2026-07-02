"""Per-researcher store of reusable published-job field values.

A researcher fills a published-job field that is bound to a named type (e.g. a
``map`` of ``CustomReplicateRule``) and saves it. The value is keyed by
``(user_id, type_key, container)`` — *not* by the published job — so the same
saved value can pre-populate any published job whose typed field uses the same
type and container shape. The resolved ``type_schema`` is denormalized onto the
record so the standalone "Saved Values" editor can render the value without a
job in hand.

A type the admin marked ``multiple`` may hold **several named cases** within one
``(user_id, type_key, container)`` group, with exactly one flagged ``is_default``
(the case that pre-fills a run form). A single-instance type has one case with an
empty ``name``. The full key is therefore ``(user_id, type_key, container, name)``.

``type_key`` is the library type name (a field's ``schema_ref``) or, for a typed
field declared inline in a job's ``definitions:`` block, the resolved schema's
own ``name``. :func:`typed_value_key` derives it from a published field so the
backend and frontend agree on the key. Plain fields are opt-in via ``saveable``
and use the published-job id, stable field id, and primitive type as their key.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from bio_pipeline_manager.models import utc_now


@dataclass(frozen=True)
class SavedTypedValueRecord:
    id: str
    user_id: str
    type_key: str
    container: str
    # A named case within the ``(user, type_key, container)`` group. Empty string for a
    # single-instance type (one value); a non-empty name for each case of a
    # multi-instance type. Exactly one case per group has ``is_default`` set.
    name: str
    is_default: bool
    label: str
    type_schema: dict[str, Any]
    value_kind: str
    field_schema: dict[str, Any]
    value: Any
    created_at: datetime
    updated_at: datetime


def typed_value_key(field: dict[str, Any]) -> tuple[str, str] | None:
    """Return ``(type_key, container)`` for a typed published field, else ``None``.

    The key is the library type name (``schema_ref``) when the field references
    the project type library, falling back to the resolved schema's ``name`` for
    a field whose type was declared inline in the job definition.
    """
    if field.get("type") != "typed":
        return None
    schema = field.get("type_schema")
    type_key = (field.get("schema_ref") or "").strip()
    if not type_key and isinstance(schema, dict):
        type_key = str(schema.get("name") or "").strip()
    if not type_key:
        return None
    container = field.get("container") or "single"
    return type_key, container


def saved_value_key(field: dict[str, Any], published_job_id: str = "") -> tuple[str, str] | None:
    """Return the reusable key for a typed field or an opted-in plain field."""
    typed_key = typed_value_key(field)
    if typed_key is not None:
        return typed_key
    if not field.get("saveable") or field.get("io_role", "none") != "none":
        return None
    field_id = str(field.get("id") or "").strip()
    field_type = str(field.get("type") or "string").strip()
    if not published_job_id or not field_id or field_type == "typed":
        return None
    return f"job:{published_job_id}:field:{field_id}:{field_type}", "single"


class _Unset:
    """Sentinel so ``update`` can tell 'leave value alone' from 'set to None'."""


_UNSET: Any = _Unset()


def _create_table_sql(table: str) -> str:
    """The current ``saved_typed_values`` schema for ``table`` (used for create + rebuild)."""
    return f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            type_key TEXT NOT NULL,
            container TEXT NOT NULL DEFAULT 'single',
            name TEXT NOT NULL DEFAULT '',
            is_default INTEGER NOT NULL DEFAULT 0,
            label TEXT NOT NULL DEFAULT '',
            type_schema TEXT NOT NULL DEFAULT '{{}}',
            value_kind TEXT NOT NULL DEFAULT 'typed',
            field_schema TEXT NOT NULL DEFAULT '{{}}',
            field_value TEXT NOT NULL DEFAULT 'null',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (user_id, type_key, container, name)
        )
    """


class SavedTypedValueStore:
    """SQLite-backed store of a researcher's saved typed values."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            # Fresh DBs get the current schema (named cases + 4-column unique key)
            # straight away; existing DBs no-op here and are migrated below.
            conn.execute(_create_table_sql("saved_typed_values"))
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(saved_typed_values)")}
            if "value_kind" not in existing:
                conn.execute("ALTER TABLE saved_typed_values ADD COLUMN value_kind TEXT NOT NULL DEFAULT 'typed'")
            if "field_schema" not in existing:
                conn.execute("ALTER TABLE saved_typed_values ADD COLUMN field_schema TEXT NOT NULL DEFAULT '{}'")
            # Named-case migration: a pre-existing table lacks ``name``. Add the two
            # columns, promote every existing (sole) row to its group's default, then
            # rebuild to swap the stale UNIQUE(user, type, container) for the 4-column
            # key — SQLite can't drop a table-level UNIQUE in place.
            if "name" not in existing:
                conn.execute("ALTER TABLE saved_typed_values ADD COLUMN name TEXT NOT NULL DEFAULT ''")
                if "is_default" not in existing:
                    conn.execute("ALTER TABLE saved_typed_values ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0")
                conn.execute("UPDATE saved_typed_values SET is_default = 1")
                columns = (
                    "id, user_id, type_key, container, name, is_default, label, "
                    "type_schema, value_kind, field_schema, field_value, created_at, updated_at"
                )
                conn.execute(_create_table_sql("saved_typed_values_rebuild"))
                conn.execute(
                    f"INSERT INTO saved_typed_values_rebuild ({columns}) "
                    f"SELECT {columns} FROM saved_typed_values"
                )
                conn.execute("DROP TABLE saved_typed_values")
                conn.execute("ALTER TABLE saved_typed_values_rebuild RENAME TO saved_typed_values")
            elif "is_default" not in existing:
                conn.execute("ALTER TABLE saved_typed_values ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0")

    def list(self, user_id: str) -> list[SavedTypedValueRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_typed_values WHERE user_id = ? "
                "ORDER BY type_key, container, is_default DESC, name",
                (user_id,),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def get(self, record_id: str) -> SavedTypedValueRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM saved_typed_values WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(f"Saved value not found: {record_id}")
        return _from_row(row)

    def get_by_key(
        self, user_id: str, type_key: str, container: str, name: str = ""
    ) -> SavedTypedValueRecord | None:
        """The exact case ``(user, type_key, container, name)``, or ``None``."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM saved_typed_values "
                "WHERE user_id = ? AND type_key = ? AND container = ? AND name = ?",
                (user_id, type_key, container, name),
            ).fetchone()
        return _from_row(row) if row is not None else None

    def get_default(self, user_id: str, type_key: str, container: str) -> SavedTypedValueRecord | None:
        """The group's default case (the one that pre-fills a run form), or ``None``.

        Falls back to the most-recently-updated case if no row is flagged default.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM saved_typed_values "
                "WHERE user_id = ? AND type_key = ? AND container = ? "
                "ORDER BY is_default DESC, updated_at DESC LIMIT 1",
                (user_id, type_key, container),
            ).fetchone()
        return _from_row(row) if row is not None else None

    def list_cases(self, user_id: str, type_key: str, container: str) -> list[SavedTypedValueRecord]:
        """Every case of one ``(user, type_key, container)`` group, default first."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_typed_values "
                "WHERE user_id = ? AND type_key = ? AND container = ? "
                "ORDER BY is_default DESC, name",
                (user_id, type_key, container),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def set_default(self, record_id: str) -> SavedTypedValueRecord:
        """Flag ``record_id`` as its group's default and clear the flag on its siblings."""
        record = self.get(record_id)
        with self.connect() as conn:
            self._clear_defaults(conn, record.user_id, record.type_key, record.container)
            conn.execute("UPDATE saved_typed_values SET is_default = 1 WHERE id = ?", (record_id,))
        return self.get(record_id)

    @staticmethod
    def _clear_defaults(conn: sqlite3.Connection, user_id: str, type_key: str, container: str) -> None:
        conn.execute(
            "UPDATE saved_typed_values SET is_default = 0 "
            "WHERE user_id = ? AND type_key = ? AND container = ?",
            (user_id, type_key, container),
        )

    def upsert(
        self,
        *,
        user_id: str,
        type_key: str,
        container: str,
        label: str,
        type_schema: dict[str, Any],
        value: Any,
        value_kind: str = "typed",
        field_schema: dict[str, Any] | None = None,
        name: str = "",
        make_default: bool = False,
    ) -> SavedTypedValueRecord:
        """Create or replace the ``name`` case of ``(user, type_key, container)``.

        The case becomes the group's default when ``make_default`` is set or the group
        has no default yet (e.g. the first case, or a single-instance type's sole
        ``name=""`` value); flagging it default clears the flag on its siblings.
        """
        now = utc_now()
        name = name or ""
        existing = self.get_by_key(user_id, type_key, container, name)
        with self.connect() as conn:
            has_default = (
                conn.execute(
                    "SELECT 1 FROM saved_typed_values "
                    "WHERE user_id = ? AND type_key = ? AND container = ? AND is_default = 1 LIMIT 1",
                    (user_id, type_key, container),
                ).fetchone()
                is not None
            )
            make_it_default = make_default or not has_default
            if make_it_default:
                self._clear_defaults(conn, user_id, type_key, container)
            if existing is not None:
                conn.execute(
                    """
                    UPDATE saved_typed_values
                    SET label = ?, type_schema = ?, value_kind = ?, field_schema = ?,
                        field_value = ?, is_default = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        label,
                        json.dumps(type_schema),
                        value_kind,
                        json.dumps(field_schema or {}),
                        json.dumps(value),
                        1 if (make_it_default or existing.is_default) else 0,
                        now.isoformat(),
                        existing.id,
                    ),
                )
                record_id = existing.id
            else:
                record_id = uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT INTO saved_typed_values (
                        id, user_id, type_key, container, name, is_default, label,
                        type_schema, value_kind, field_schema, field_value, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        user_id,
                        type_key,
                        container,
                        name,
                        1 if make_it_default else 0,
                        label,
                        json.dumps(type_schema),
                        value_kind,
                        json.dumps(field_schema or {}),
                        json.dumps(value),
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
        # Read back only after the write has committed (the with-block exit), so a
        # fresh connection sees the new value rather than the pre-update row.
        return self.get(record_id)

    def update(
        self,
        record_id: str,
        *,
        value: Any = _UNSET,
        label: str | None = None,
        name: str | None = None,
        make_default: bool | None = None,
    ) -> SavedTypedValueRecord:
        """Update a saved case's value, label, name, and/or default flag by id.

        Renaming is rejected when another case in the same group already uses the new
        name. ``make_default=True`` flags this case default (clearing its siblings);
        ``False``/``None`` leaves the flag untouched — a group always keeps one default.
        """
        current = self.get(record_id)
        next_value = current.value if value is _UNSET else value
        next_label = current.label if label is None else label
        next_name = current.name if name is None else (name or "")
        if next_name != current.name:
            clash = self.get_by_key(current.user_id, current.type_key, current.container, next_name)
            if clash is not None and clash.id != record_id:
                raise ValueError(f"A case named '{next_name}' already exists for this type")
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE saved_typed_values
                SET field_value = ?, label = ?, name = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(next_value), next_label, next_name, utc_now().isoformat(), record_id),
            )
        if make_default:
            return self.set_default(record_id)
        return self.get(record_id)

    def delete(self, record_id: str) -> None:
        """Delete a case; if it was the default, promote a remaining sibling."""
        record = self.get(record_id)
        with self.connect() as conn:
            conn.execute("DELETE FROM saved_typed_values WHERE id = ?", (record_id,))
            if record.is_default:
                heir = conn.execute(
                    "SELECT id FROM saved_typed_values "
                    "WHERE user_id = ? AND type_key = ? AND container = ? "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (record.user_id, record.type_key, record.container),
                ).fetchone()
                if heir is not None:
                    conn.execute("UPDATE saved_typed_values SET is_default = 1 WHERE id = ?", (heir["id"],))


def _from_row(row: sqlite3.Row) -> SavedTypedValueRecord:
    return SavedTypedValueRecord(
        id=row["id"],
        user_id=row["user_id"],
        type_key=row["type_key"],
        container=row["container"],
        name=row["name"],
        is_default=bool(row["is_default"]),
        label=row["label"],
        type_schema=json.loads(row["type_schema"] or "{}"),
        value_kind=row["value_kind"] or "typed",
        field_schema=json.loads(row["field_schema"] or "{}"),
        value=json.loads(row["field_value"] or "null"),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
