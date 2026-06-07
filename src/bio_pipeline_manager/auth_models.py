from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


@dataclass(frozen=True)
class UserRecord:
    id: str
    username: str
    display_name: str
    password_hash: str
    role: Role
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None


@dataclass(frozen=True)
class SessionRecord:
    id: str
    user_id: str
    token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
