"""Filesystem-backed storage for reusable Job Definition YAML files.

Mirrors :class:`bio_pipeline_manager.yaml_store.YamlStore` (path-safe CRUD,
folders, tree) but for *Job Definitions* (validated with
:func:`bio_pipeline_manager.job_definition.parse_job_definition`) and with
soft **archive** support: archived definitions move to a sibling root and are
recoverable via :meth:`restore`.
"""

from __future__ import annotations

from pathlib import Path

from bio_pipeline_manager.job_definition import JobDefinitionError, parse_job_definition


def _resolve_name(root: Path, name: str) -> Path:
    candidate = Path(name)
    if candidate.suffix not in {".yaml", ".yml"}:
        candidate = candidate.with_suffix(".yaml")
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("Definition name must be relative and stay inside the store")
    path = (root / candidate).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Definition name resolves outside the store")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_folder(root: Path, folder: str) -> Path:
    candidate = Path(folder)
    if str(candidate) in {"", "."}:
        return root.resolve()
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("Folder path must be relative and stay inside the store")
    path = (root / candidate).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Folder path resolves outside the store")
    return path


class JobDefinitionStore:
    """Active + archived Job Definition files on disk."""

    def __init__(self, root: str | Path, archive_root: str | Path | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.archive_root = Path(archive_root) if archive_root else Path(f"{self.root}_archive")
        self.archive_root.mkdir(parents=True, exist_ok=True)

    # --- queries -------------------------------------------------------- #
    def list(self) -> list[Path]:
        return sorted([*self.root.rglob("*.yaml"), *self.root.rglob("*.yml")])

    def list_archived(self) -> list[Path]:
        return sorted([*self.archive_root.rglob("*.yaml"), *self.archive_root.rglob("*.yml")])

    def relative_name(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def relative_archived_name(self, path: Path) -> str:
        return path.resolve().relative_to(self.archive_root.resolve()).as_posix()

    def load(self, name: str) -> str:
        return _resolve_name(self.root, name).read_text(encoding="utf-8")

    def job_name(self, name: str) -> str:
        """The Job Definition's declared ``job`` name (raises if invalid)."""
        return parse_job_definition(self.load(name)).name

    # --- mutations ------------------------------------------------------ #
    def save(self, name: str, content: str, *, overwrite: bool = False) -> Path:
        self.validate_content(content)
        path = _resolve_name(self.root, name)
        if path.exists() and not overwrite:
            raise FileExistsError(f"Definition already exists: {path}")
        path.write_text(content, encoding="utf-8")
        return path

    def create_folder(self, folder: str) -> Path:
        path = _resolve_folder(self.root, folder)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def delete_folder(self, folder: str) -> None:
        path = _resolve_folder(self.root, folder)
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"Folder not found: {folder}")
        if any(path.iterdir()):
            raise ValueError(f"Folder is not empty: {folder}")
        path.rmdir()

    def delete_file(self, name: str, *, archived: bool = False) -> None:
        base = self.archive_root if archived else self.root
        path = _resolve_name(base, name)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Definition not found: {name}")
        path.unlink()
        self._cleanup_empty_parents(base, path.parent)

    def move_file(self, source_name: str, destination_name: str, *, overwrite: bool = False) -> Path:
        source_path = _resolve_name(self.root, source_name)
        destination_path = _resolve_name(self.root, destination_name)
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Definition not found: {source_name}")
        if destination_path.exists() and source_path.resolve() != destination_path.resolve() and not overwrite:
            raise FileExistsError(f"Definition already exists: {destination_path}")
        if source_path.resolve() == destination_path.resolve():
            return source_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.replace(destination_path)
        self._cleanup_empty_parents(self.root, source_path.parent)
        return destination_path

    def archive(self, name: str) -> Path:
        """Soft-retire a definition: move it to the archive root (recoverable)."""
        source = _resolve_name(self.root, name)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"Definition not found: {name}")
        target = _resolve_name(self.archive_root, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
        self._cleanup_empty_parents(self.root, source.parent)
        return target

    def restore(self, name: str) -> Path:
        """Bring an archived definition back into the active store."""
        source = _resolve_name(self.archive_root, name)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"Archived definition not found: {name}")
        target = _resolve_name(self.root, name)
        if target.exists():
            raise FileExistsError(f"Definition already exists: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
        self._cleanup_empty_parents(self.archive_root, source.parent)
        return target

    # --- validation ----------------------------------------------------- #
    @staticmethod
    def validate_content(content: str) -> None:
        # parse_job_definition raises JobDefinitionError (a ValueError subclass).
        parse_job_definition(content)

    def summary(self, name: str, *, archived: bool = False) -> tuple[str, str, bool, str | None]:
        """Return ``(job_name, description, is_valid, error)`` for a stored definition."""
        base = self.archive_root if archived else self.root
        content = _resolve_name(base, name).read_text(encoding="utf-8")
        try:
            parsed = parse_job_definition(content)
            return parsed.name, parsed.description, True, None
        except JobDefinitionError as exc:
            return "", "", False, str(exc)

    def _cleanup_empty_parents(self, base: Path, path: Path) -> None:
        root = base.resolve()
        current = path.resolve()
        while current != root:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
