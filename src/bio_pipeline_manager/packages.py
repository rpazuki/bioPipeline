"""Package management: install/uninstall science + pipeline packages.

The manager owns the pipeline engine but resolves process functions
(``package: labUtils.*`` etc.) by import at run time, so users need a way to
provision those packages into the backend's Python environment. This module
installs into **the same interpreter the Task runner uses** (``sys.executable``),
records an audit trail, and refuses to mutate the environment while jobs run.

The actual ``pip`` invocation is injectable (``pip_runner``) so it can be tested
without touching the real environment.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import re
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

PipRunner = Callable[[str, list[str]], "tuple[int, str, str]"]

# Source kinds a user can request.
SOURCE_TYPES = {"pypi", "git", "editable", "requirements"}


class PackageError(RuntimeError):
    """A package operation could not be performed (bad request / unsupported)."""


class PackageBusyError(PackageError):
    """Raised when an install is attempted while jobs are running."""


@dataclass(frozen=True)
class PackageOpResult:
    id: str
    action: str  # "install" | "uninstall"
    spec: str
    source_type: str
    resolved_version: str | None
    exit_code: int
    ok: bool
    stdout: str
    stderr: str
    actor: str
    created_at: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_pip_runner(python_executable: str, args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        [python_executable, "-m", "pip", *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def distribution_name(spec: str, source_type: str) -> str | None:
    """Best-effort extraction of the installed distribution name from a spec.

    Returns None when it cannot be determined (e.g. editable paths or
    requirements files), in which case the resolved version is left unknown.
    """
    if source_type in {"editable", "requirements"}:
        return None
    spec = spec.strip()
    if "@" in spec:  # "name @ git+https://..."
        return spec.split("@", 1)[0].strip() or None
    egg = re.search(r"[#&]egg=([A-Za-z0-9_.\-]+)", spec)
    if egg:
        return egg.group(1)
    if spec.startswith(("git+", "http://", "https://", "file:")):
        return None
    # "name==1.2.0", "name>=1", "name[extra]" -> "name"
    return re.split(r"[<>=!~\[ ]", spec, maxsplit=1)[0].strip() or None


class InstallStore:
    """SQLite-backed audit log of package operations."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS installs (
                    id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    spec TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    resolved_version TEXT,
                    exit_code INTEGER NOT NULL,
                    ok INTEGER NOT NULL,
                    stdout TEXT NOT NULL,
                    stderr TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def record(self, result: PackageOpResult) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO installs (
                    id, action, spec, source_type, resolved_version,
                    exit_code, ok, stdout, stderr, actor, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.id,
                    result.action,
                    result.spec,
                    result.source_type,
                    result.resolved_version,
                    result.exit_code,
                    1 if result.ok else 0,
                    result.stdout,
                    result.stderr,
                    result.actor,
                    result.created_at,
                ),
            )

    def history(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM installs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{**dict(row), "ok": bool(row["ok"])} for row in rows]


class PackageManager:
    """Install/uninstall packages into the backend interpreter, with audit."""

    def __init__(
        self,
        store: InstallStore,
        *,
        python_executable: str | None = None,
        pip_runner: PipRunner | None = None,
        job_guard: Callable[[], bool] | None = None,
    ):
        self.store = store
        self.python_executable = python_executable or sys.executable
        self.pip_runner = pip_runner or _default_pip_runner
        # job_guard() returns True when jobs are running (installs are refused).
        self.job_guard = job_guard

    def list_installed(self) -> list[dict[str, str]]:
        # importlib.metadata can yield the same distribution name more than once
        # (e.g. an editable install alongside its .egg-info), so dedupe by name.
        packages: dict[str, dict[str, str]] = {}
        for dist in importlib.metadata.distributions():
            name = dist.metadata["Name"] if dist.metadata else None
            if name and name.lower() not in packages:
                packages[name.lower()] = {"name": name, "version": dist.version or ""}
        return sorted(packages.values(), key=lambda item: item["name"].lower())

    def installed_version(self, name: str) -> str | None:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    def _guard_against_running_jobs(self) -> None:
        if self.job_guard and self.job_guard():
            raise PackageBusyError("Cannot change packages while jobs are running")

    def _pip_args_for_install(self, spec: str, source_type: str) -> list[str]:
        if source_type not in SOURCE_TYPES:
            raise PackageError(f"Unsupported source_type '{source_type}'")
        if not spec.strip():
            raise PackageError("A package spec is required")
        if source_type == "editable":
            return ["install", "-e", spec]
        if source_type == "requirements":
            return ["install", "-r", spec]
        # pypi and git both pass the spec straight through to pip.
        return ["install", spec]

    def install(self, spec: str, *, source_type: str = "pypi", actor: str = "cli") -> PackageOpResult:
        self._guard_against_running_jobs()
        args = self._pip_args_for_install(spec, source_type)
        exit_code, stdout, stderr = self.pip_runner(self.python_executable, args)
        importlib.invalidate_caches()

        ok = exit_code == 0
        name = distribution_name(spec, source_type)
        resolved_version = self.installed_version(name) if ok and name else None
        result = PackageOpResult(
            id=uuid.uuid4().hex,
            action="install",
            spec=spec,
            source_type=source_type,
            resolved_version=resolved_version,
            exit_code=exit_code,
            ok=ok,
            stdout=stdout,
            stderr=stderr,
            actor=actor,
            created_at=_utc_now_iso(),
        )
        self.store.record(result)
        return result

    def uninstall(self, name: str, *, actor: str = "cli") -> PackageOpResult:
        self._guard_against_running_jobs()
        if not name.strip():
            raise PackageError("A package name is required")
        exit_code, stdout, stderr = self.pip_runner(self.python_executable, ["uninstall", "-y", name])
        importlib.invalidate_caches()

        result = PackageOpResult(
            id=uuid.uuid4().hex,
            action="uninstall",
            spec=name,
            source_type="pypi",
            resolved_version=None,
            exit_code=exit_code,
            ok=exit_code == 0,
            stdout=stdout,
            stderr=stderr,
            actor=actor,
            created_at=_utc_now_iso(),
        )
        self.store.record(result)
        return result


def result_dict(result: PackageOpResult) -> dict:
    return asdict(result)
