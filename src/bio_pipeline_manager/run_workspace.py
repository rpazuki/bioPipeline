"""Per-run upload/output workspaces for published-job runs.

Each run gets an isolated ``<runs_root>/<workspace_id>/{inputs,outputs}`` tree
plus a ``manifest.json`` recording its owner. Researchers upload their inputs
into this workspace and the job writes its outputs here; at execution the
published-job field values are rewritten to point at these concrete paths
(:func:`bio_pipeline_manager.published_jobs.resolve_io`).

Security: every path derived from caller-supplied input (the workspace id, an
upload filename, an uploaded-file handle) is containment-checked against the
workspace root, mirroring the path-safety idiom in
:mod:`bio_pipeline_manager.yaml_store`. A workspace can therefore never read or
write outside its own directory, and the server filesystem is never exposed.
"""

from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from bio_pipeline_manager.models import utc_now

# Per-run upload budget. Phase 6 will make this configurable + add resumable
# chunking; for now it bounds a single run's workspace.
DEFAULT_MAX_WORKSPACE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


class RunWorkspaceError(ValueError):
    """Raised for an invalid workspace id, path escape, or quota breach."""


@dataclass(frozen=True)
class WorkspaceManifest:
    workspace_id: str
    owner_user_id: str
    published_job_id: str
    created_at: str


def _safe_segment(segment: str) -> str:
    """Last path component of ``segment`` with both separators stripped."""
    name = str(segment).replace("\\", "/").split("/")[-1]
    if not name or name in {".", ".."}:
        raise RunWorkspaceError("Invalid path segment")
    return name


def _safe_relpath(relpath: str) -> str:
    """Normalise a multi-segment relative path, refusing any escape.

    Used for directory uploads (a file's ``webkitRelativePath``). Keeps nested
    structure but strips ``.``/empty segments and rejects ``..``.
    """
    parts = [part for part in str(relpath).replace("\\", "/").split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise RunWorkspaceError("Invalid relative path")
    return "/".join(parts)


class RunWorkspaceStore:
    def __init__(self, root: str | Path, *, max_bytes: int = DEFAULT_MAX_WORKSPACE_BYTES):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes

    # -- creation / lookup --------------------------------------------------
    def create(self, *, owner_user_id: str, published_job_id: str) -> WorkspaceManifest:
        workspace_id = uuid.uuid4().hex
        workspace = self.root / workspace_id
        (workspace / "inputs").mkdir(parents=True)
        (workspace / "outputs").mkdir(parents=True)
        manifest = WorkspaceManifest(
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            published_job_id=published_job_id,
            created_at=utc_now().isoformat(),
        )
        (workspace / "manifest.json").write_text(json.dumps(asdict(manifest), sort_keys=True), encoding="utf-8")
        return manifest

    def _workspace_dir(self, workspace_id: str) -> Path:
        if not workspace_id or _safe_segment(workspace_id) != workspace_id:
            raise RunWorkspaceError("Invalid workspace id")
        resolved = (self.root / workspace_id).resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise RunWorkspaceError("Workspace resolves outside the runs root")
        if not resolved.is_dir():
            raise RunWorkspaceError(f"Workspace not found: {workspace_id}")
        return resolved

    def manifest(self, workspace_id: str) -> WorkspaceManifest:
        workspace = self._workspace_dir(workspace_id)
        try:
            data = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RunWorkspaceError(f"Workspace manifest unreadable: {workspace_id}") from exc
        return WorkspaceManifest(**data)

    def require_owner(self, workspace_id: str, user_id: str) -> WorkspaceManifest:
        manifest = self.manifest(workspace_id)
        if manifest.owner_user_id != user_id:
            raise RunWorkspaceError("Workspace belongs to another user")
        return manifest

    # -- containment --------------------------------------------------------
    def safe_path(self, workspace_id: str, relative: str) -> Path:
        """Resolve a workspace-relative path, refusing any escape."""
        workspace = self._workspace_dir(workspace_id)
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise RunWorkspaceError("Path must stay inside the workspace")
        resolved = (workspace / candidate).resolve()
        if not resolved.is_relative_to(workspace):
            raise RunWorkspaceError("Path resolves outside the workspace")
        return resolved

    # -- inputs / outputs ---------------------------------------------------
    def prepare_input(self, workspace_id: str, field_id: str, filename: str, relpath: str = "") -> tuple[Path, str]:
        """Return ``(dest_path, workspace_relative_handle)`` for an upload.

        The caller streams the body into ``dest_path`` (enforcing
        :attr:`max_bytes` against :meth:`total_size`). A ``relpath`` (a file's
        position within an uploaded folder) preserves the directory structure;
        otherwise the file lands directly under ``inputs/<field_id>``.
        """
        if relpath:
            rel = f"inputs/{_safe_segment(field_id)}/{_safe_relpath(relpath)}"
        else:
            rel = f"inputs/{_safe_segment(field_id)}/{_safe_segment(filename)}"
        dest = self.safe_path(workspace_id, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        return dest, rel

    def input_abspath(self, workspace_id: str, handle: str) -> Path:
        path = self.safe_path(workspace_id, handle)
        if not path.exists():
            raise RunWorkspaceError(f"Uploaded file not found: {handle}")
        return path

    def input_dir(self, workspace_id: str, field_id: str) -> Path:
        """The directory holding a field's uploaded folder (must be non-empty)."""
        path = self.safe_path(workspace_id, f"inputs/{_safe_segment(field_id)}")
        if not path.is_dir() or not any(path.iterdir()):
            raise RunWorkspaceError("No files were uploaded for this folder field")
        return path

    def output_dir(self, workspace_id: str, field_id: str) -> Path:
        path = self.safe_path(workspace_id, f"outputs/{_safe_segment(field_id)}")
        path.mkdir(parents=True, exist_ok=True)
        return path

    # -- delivery / reaping -------------------------------------------------
    def exists(self, workspace_id: str) -> bool:
        try:
            return (self.root / _safe_segment(workspace_id)).is_dir()
        except RunWorkspaceError:
            return False

    def artifact_path(self, workspace_id: str) -> Path:
        return self._workspace_dir(workspace_id) / "artifact.zip"

    def has_artifact(self, workspace_id: str) -> bool:
        try:
            return self.artifact_path(workspace_id).is_file()
        except RunWorkspaceError:
            return False

    def package_outputs(self, workspace_id: str) -> Path | None:
        """Zip the ``outputs`` subtree into ``artifact.zip``; ``None`` if empty."""
        workspace = self._workspace_dir(workspace_id)
        outputs = workspace / "outputs"
        files = [p for p in outputs.rglob("*") if p.is_file()] if outputs.is_dir() else []
        if not files:
            return None
        artifact = workspace / "artifact.zip"
        with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                archive.write(file, file.relative_to(outputs).as_posix())
        return artifact

    def clear_inputs(self, workspace_id: str) -> None:
        inputs = self._workspace_dir(workspace_id) / "inputs"
        shutil.rmtree(inputs, ignore_errors=True)
        inputs.mkdir(parents=True, exist_ok=True)

    def clear_outputs(self, workspace_id: str) -> None:
        """Drop the raw ``outputs`` subtree (kept in ``artifact.zip`` after packaging)."""
        outputs = self._workspace_dir(workspace_id) / "outputs"
        shutil.rmtree(outputs, ignore_errors=True)
        outputs.mkdir(parents=True, exist_ok=True)

    def clone_inputs(self, source_workspace_id: str, *, owner_user_id: str, published_job_id: str) -> WorkspaceManifest:
        """Create a fresh workspace seeded with a copy of another's ``inputs`` subtree.

        Used to replay a run (rewind) or fire a recurring schedule: each occurrence
        gets its own output space while reusing the originally-provided inputs, whose
        upload handles (``inputs/<field>/<file>``) are preserved by the copy so the
        stored ``file_bindings`` still resolve.
        """
        source = self._workspace_dir(source_workspace_id)
        manifest = self.create(owner_user_id=owner_user_id, published_job_id=published_job_id)
        dest = self.root / manifest.workspace_id
        source_inputs = source / "inputs"
        if source_inputs.is_dir():
            shutil.copytree(source_inputs, dest / "inputs", dirs_exist_ok=True)
        return manifest

    def has_inputs(self, workspace_id: str) -> bool:
        try:
            inputs = self._workspace_dir(workspace_id) / "inputs"
        except RunWorkspaceError:
            return False
        return inputs.is_dir() and any(inputs.rglob("*"))

    def mark_reaped(self, workspace_id: str) -> None:
        (self._workspace_dir(workspace_id) / ".reaped").write_text(utc_now().isoformat(), encoding="utf-8")

    def reaped_at(self, workspace_id: str) -> datetime | None:
        marker = self._workspace_dir(workspace_id) / ".reaped"
        if not marker.is_file():
            return None
        try:
            return datetime.fromisoformat(marker.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def total_size(self, workspace_id: str) -> int:
        """Bytes of run *data* (the ``inputs``/``outputs`` subtrees).

        Excludes ``manifest.json`` so server bookkeeping never eats the
        researcher's upload budget.
        """
        workspace = self._workspace_dir(workspace_id)
        total = 0
        for sub in ("inputs", "outputs"):
            base = workspace / sub
            if base.is_dir():
                total += sum(item.stat().st_size for item in base.rglob("*") if item.is_file())
        return total

    def delete(self, workspace_id: str) -> None:
        shutil.rmtree(self._workspace_dir(workspace_id), ignore_errors=True)
