"""Allowlisted shared-storage roots and secure browsing.

Some published-job inputs already live on a network share that the backend host
also mounts (e.g. ``H:/ROBOT_SCIENTIST/E_coli``). Rather than upload that data
or expose the whole server filesystem, an admin declares a small set of named
*roots* (config-backed). Researchers may browse and pick paths **only within**
those roots; every caller-supplied sub-path is containment-checked, mirroring
the path-safety idiom in :mod:`bio_pipeline_manager.yaml_store`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SharedStorageError(ValueError):
    """Raised for an unknown root or a path that escapes its root."""


@dataclass(frozen=True)
class SharedRoot:
    id: str
    label: str
    path: Path


@dataclass(frozen=True)
class SharedEntry:
    name: str
    path: str  # root-relative POSIX path
    kind: str  # "file" | "directory"


class SharedStorage:
    def __init__(self, roots: list[dict[str, Any]] | None = None):
        self.roots: dict[str, SharedRoot] = {}
        for raw in roots or []:
            if not isinstance(raw, dict) or "id" not in raw or "path" not in raw:
                continue
            root_id = str(raw["id"])
            self.roots[root_id] = SharedRoot(
                id=root_id,
                label=str(raw.get("label", root_id)),
                path=Path(str(raw["path"])).expanduser(),
            )

    def list_roots(self) -> list[SharedRoot]:
        return list(self.roots.values())

    def get_root(self, root_id: str) -> SharedRoot:
        root = self.roots.get(root_id)
        if root is None:
            raise SharedStorageError(f"Unknown shared root: {root_id}")
        return root

    def _safe_target(self, root: SharedRoot, subpath: str) -> Path:
        candidate = Path(subpath or "")
        if candidate.is_absolute() or ".." in candidate.parts:
            raise SharedStorageError("Path must stay inside the shared root")
        resolved = (root.path / candidate).resolve()
        if not resolved.is_relative_to(root.path.resolve()):
            raise SharedStorageError("Path resolves outside the shared root")
        return resolved

    def browse(self, root_id: str, subpath: str = "") -> list[SharedEntry]:
        root = self.get_root(root_id)
        target = self._safe_target(root, subpath)
        if not target.is_dir():
            raise SharedStorageError("Not a browsable directory")
        root_resolved = root.path.resolve()
        entries: list[SharedEntry] = []
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            relative = item.resolve().relative_to(root_resolved).as_posix()
            entries.append(
                SharedEntry(name=item.name, path=relative, kind="directory" if item.is_dir() else "file")
            )
        return entries

    def resolve(self, root_id: str, subpath: str) -> Path:
        root = self.get_root(root_id)
        target = self._safe_target(root, subpath)
        if not target.exists():
            raise SharedStorageError(f"Path not found in shared storage: {subpath}")
        return target

    def write_target(self, root_id: str, subpath: str) -> Path:
        """A containment-checked, created directory under a root for shared-write outputs."""
        root = self.get_root(root_id)
        target = self._safe_target(root, subpath)
        target.mkdir(parents=True, exist_ok=True)
        return target
