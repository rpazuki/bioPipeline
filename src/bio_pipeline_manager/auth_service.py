from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta

from bio_pipeline_manager.auth_models import Role, SessionRecord, UserRecord
from bio_pipeline_manager.auth_store import AuthStore
from bio_pipeline_manager.models import utc_now

_HASH_ALGORITHM = "pbkdf2_sha256"
_HASH_ITERATIONS = 310_000
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


class AuthError(ValueError):
    """Raised when an authentication or user-management action is invalid."""


@dataclass(frozen=True)
class LoginResult:
    user: UserRecord
    session: SessionRecord
    token: str


def normalize_username(username: str) -> str:
    username = username.strip()
    if not _USERNAME_RE.fullmatch(username):
        raise AuthError("Username must be 3-64 characters using letters, numbers, dots, dashes, or underscores")
    return username


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _HASH_ITERATIONS)
    return "$".join(
        [
            _HASH_ALGORITHM,
            str(_HASH_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = stored_hash.split("$", 3)
        if algorithm != _HASH_ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_text.encode("ascii"))
        expected = base64.b64decode(digest_text.encode("ascii"))
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self, store: AuthStore, *, session_ttl_hours: float = 24.0):
        self.store = store
        self.session_ttl = timedelta(hours=session_ttl_hours)

    def create_user(
        self,
        *,
        username: str,
        password: str,
        role: Role,
        display_name: str = "",
        is_active: bool = True,
    ) -> UserRecord:
        username = normalize_username(username)
        if self.store.get_user_by_username(username):
            raise AuthError("Username already exists")
        return self.store.create_user(
            username=username,
            display_name=display_name.strip(),
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )

    def bootstrap_admin(self, *, username: str, password: str, display_name: str = "") -> UserRecord:
        if self.store.admin_exists():
            raise AuthError("An active admin already exists")
        return self.create_user(
            username=username,
            display_name=display_name,
            password=password,
            role=Role.ADMIN,
            is_active=True,
        )

    def authenticate(self, *, username: str, password: str) -> LoginResult:
        username = normalize_username(username)
        user = self.store.get_user_by_username(username)
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise AuthError("Invalid username or password")
        token = secrets.token_urlsafe(32)
        session = self.store.create_session(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=utc_now() + self.session_ttl,
        )
        self.store.mark_login(user.id)
        return LoginResult(user=self.store.get_user(user.id), session=session, token=token)

    def user_for_token(self, token: str | None) -> tuple[UserRecord, SessionRecord] | None:
        if not token:
            return None
        session = self.store.get_session_by_token_hash(hash_session_token(token))
        if session is None or session.revoked_at is not None or session.expires_at <= utc_now():
            return None
        try:
            user = self.store.get_user(session.user_id)
        except KeyError:
            return None
        if not user.is_active:
            return None
        return user, session

    def logout(self, token: str | None) -> None:
        resolved = self.user_for_token(token)
        if resolved is not None:
            _, session = resolved
            self.store.revoke_session(session.id)

    def list_users(self) -> list[UserRecord]:
        return self.store.list_users()

    def get_user(self, user_id: str) -> UserRecord:
        return self.store.get_user(user_id)

    def update_user(
        self,
        user_id: str,
        *,
        username: str | None = None,
        display_name: str | None = None,
        role: Role | None = None,
        is_active: bool | None = None,
    ) -> UserRecord:
        if username is not None:
            username = normalize_username(username)
            existing = self.store.get_user_by_username(username)
            if existing and existing.id != user_id:
                raise AuthError("Username already exists")
        user = self.store.update_user(
            user_id,
            username=username,
            display_name=display_name.strip() if display_name is not None else None,
            role=role,
            is_active=is_active,
        )
        if is_active is False:
            self.store.revoke_user_sessions(user_id)
        return user

    def reset_password(self, user_id: str, password: str) -> UserRecord:
        user = self.store.update_user(user_id, password_hash=hash_password(password))
        self.store.revoke_user_sessions(user_id)
        return user

    def disable_user(self, user_id: str) -> UserRecord:
        return self.update_user(user_id, is_active=False)

    def enable_user(self, user_id: str) -> UserRecord:
        return self.update_user(user_id, is_active=True)
