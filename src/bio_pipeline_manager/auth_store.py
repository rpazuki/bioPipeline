from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from bio_pipeline_manager.auth_models import Role, SessionRecord, UserRecord
from bio_pipeline_manager.models import as_utc, utc_now


class AuthStore:
    """SQLite-backed users and opaque sessions."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def init(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def create_user(
        self,
        *,
        username: str,
        password_hash: str,
        role: Role,
        display_name: str = "",
        is_active: bool = True,
    ) -> UserRecord:
        user_id = uuid.uuid4().hex
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users (
                    id, username, display_name, password_hash, role, is_active,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    username,
                    display_name,
                    password_hash,
                    role.value,
                    1 if is_active else 0,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return self.get_user(user_id)

    def list_users(self) -> list[UserRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY username COLLATE NOCASE").fetchall()
        return [self._row_to_user(row) for row in rows]

    def get_user(self, user_id: str) -> UserRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise KeyError(f"User not found: {user_id}")
        return self._row_to_user(row)

    def get_user_by_username(self, username: str) -> UserRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE lower(username) = lower(?)",
                (username,),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def admin_exists(self) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM users WHERE role = ? AND is_active = 1 LIMIT 1",
                (Role.ADMIN.value,),
            ).fetchone()
        return row is not None

    def update_user(
        self,
        user_id: str,
        *,
        username: str | None = None,
        display_name: str | None = None,
        role: Role | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
    ) -> UserRecord:
        current = self.get_user(user_id)
        values = {
            "username": username if username is not None else current.username,
            "display_name": display_name if display_name is not None else current.display_name,
            "role": role.value if role is not None else current.role.value,
            "is_active": 1 if (is_active if is_active is not None else current.is_active) else 0,
            "password_hash": password_hash if password_hash is not None else current.password_hash,
            "updated_at": utc_now().isoformat(),
            "id": user_id,
        }
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET username = :username,
                    display_name = :display_name,
                    role = :role,
                    is_active = :is_active,
                    password_hash = :password_hash,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                values,
            )
        return self.get_user(user_id)

    def mark_login(self, user_id: str) -> None:
        now = utc_now().isoformat()
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                (now, now, user_id),
            )

    def create_session(self, *, user_id: str, token_hash: str, expires_at: datetime) -> SessionRecord:
        session_id = uuid.uuid4().hex
        now = utc_now()
        expires_at = as_utc(expires_at)
        if expires_at is None:
            raise ValueError("expires_at is required")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, user_id, token_hash, now.isoformat(), expires_at.isoformat()),
            )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> SessionRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(f"Session not found: {session_id}")
        return self._row_to_session(row)

    def get_session_by_token_hash(self, token_hash: str) -> SessionRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        return self._row_to_session(row) if row else None

    def touch_session(self, session_id: str, *, expires_at: datetime) -> None:
        """Extend an active (non-revoked) session's expiry.

        Used by sliding-expiration renewal so a steadily-used session never
        lapses mid-use. A revoked session is intentionally left untouched.
        """
        expires_at = as_utc(expires_at)
        if expires_at is None:
            raise ValueError("expires_at is required")
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE id = ? AND revoked_at IS NULL",
                (expires_at.isoformat(), session_id),
            )

    def revoke_session(self, session_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET revoked_at = COALESCE(revoked_at, ?) WHERE id = ?",
                (utc_now().isoformat(), session_id),
            )

    def revoke_user_sessions(self, user_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET revoked_at = COALESCE(revoked_at, ?) WHERE user_id = ?",
                (utc_now().isoformat(), user_id),
            )

    def _row_to_user(self, row: sqlite3.Row) -> UserRecord:
        return UserRecord(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"],
            password_hash=row["password_hash"],
            role=Role(row["role"]),
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_login_at=datetime.fromisoformat(row["last_login_at"]) if row["last_login_at"] else None,
        )

    def _row_to_session(self, row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            id=row["id"],
            user_id=row["user_id"],
            token_hash=row["token_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            revoked_at=datetime.fromisoformat(row["revoked_at"]) if row["revoked_at"] else None,
        )
