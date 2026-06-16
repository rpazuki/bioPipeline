"""Per-researcher store of reusable published-job field values.

A researcher fills a published-job field that is bound to a named type (e.g. a
``map`` of ``CustomReplicateRule``) and saves it. The value is keyed by
``(user_id, type_key, container)`` — *not* by the published job — so the same
saved value can pre-populate any published job whose typed field uses the same
type and container shape. The resolved ``type_schema`` is denormalized onto the
record so the standalone "Saved Values" editor can render the value without a
job in hand.

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_typed_values (
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
            )
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(saved_typed_values)")}
            if "value_kind" not in existing:
                conn.execute("ALTER TABLE saved_typed_values ADD COLUMN value_kind TEXT NOT NULL DEFAULT 'typed'")
            if "field_schema" not in existing:
                conn.execute("ALTER TABLE saved_typed_values ADD COLUMN field_schema TEXT NOT NULL DEFAULT '{}'")

    def list(self, user_id: str) -> list[SavedTypedValueRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_typed_values WHERE user_id = ? ORDER BY type_key, container",
                (user_id,),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def get(self, record_id: str) -> SavedTypedValueRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM saved_typed_values WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(f"Saved value not found: {record_id}")
        return _from_row(row)

    def get_by_key(self, user_id: str, type_key: str, container: str) -> SavedTypedValueRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM saved_typed_values WHERE user_id = ? AND type_key = ? AND container = ?",
                (user_id, type_key, container),
            ).fetchone()
        return _from_row(row) if row is not None else None

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
    ) -> SavedTypedValueRecord:
        """Create or replace the saved value for ``(user, type_key, container)``."""
        now = utc_now()
        existing = self.get_by_key(user_id, type_key, container)
        if existing is not None:
            with self.connect() as conn:
                conn.execute(
                    """
                    UPDATE saved_typed_values
                    SET label = ?, type_schema = ?, value_kind = ?, field_schema = ?,
                        field_value = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        label,
                        json.dumps(type_schema),
                        value_kind,
                        json.dumps(field_schema or {}),
                        json.dumps(value),
                        now.isoformat(),
                        existing.id,
                    ),
                )
            # Read back only after the write has committed (the with-block exit), so a
            # fresh connection sees the new value rather than the pre-update row.
            return self.get(existing.id)
        record_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO saved_typed_values (
                    id, user_id, type_key, container, label, type_schema,
                    value_kind, field_schema, field_value, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    user_id,
                    type_key,
                    container,
                    label,
                    json.dumps(type_schema),
                    value_kind,
                    json.dumps(field_schema or {}),
                    json.dumps(value),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return self.get(record_id)

    def update(
        self,
        record_id: str,
        *,
        value: Any = _UNSET,
        label: str | None = None,
    ) -> SavedTypedValueRecord:
        """Update an existing saved value's value and/or label by id."""
        current = self.get(record_id)
        next_value = current.value if value is _UNSET else value
        next_label = current.label if label is None else label
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE saved_typed_values
                SET field_value = ?, label = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(next_value), next_label, utc_now().isoformat(), record_id),
            )
        return self.get(record_id)

    def delete(self, record_id: str) -> None:
        self.get(record_id)
        with self.connect() as conn:
            conn.execute("DELETE FROM saved_typed_values WHERE id = ?", (record_id,))


def _from_row(row: sqlite3.Row) -> SavedTypedValueRecord:
    return SavedTypedValueRecord(
        id=row["id"],
        user_id=row["user_id"],
        type_key=row["type_key"],
        container=row["container"],
        label=row["label"],
        type_schema=json.loads(row["type_schema"] or "{}"),
        value_kind=row["value_kind"] or "typed",
        field_schema=json.loads(row["field_schema"] or "{}"),
        value=json.loads(row["field_value"] or "null"),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
