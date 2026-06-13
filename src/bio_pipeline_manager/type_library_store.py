"""Filesystem-backed storage for the project-level type library.

The whole library lives in one human-readable YAML file (a mapping of type name ->
``{description, fields}``). It is small and read/written by the single backend
process, so a load-modify-write per mutation is sufficient. Every write is validated
as a *whole library* (so cross-type references and cycles are caught) via
:func:`bio_pipeline_manager.type_schema.validate_library`.

Surfaced on the Environment page alongside package management: the Python packages a
type is extracted from are installed there, so the types derived from them live there
too.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from bio_pipeline_manager.type_schema import TypeSchemaError, validate_library

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class TypeLibraryStore:
    """The project type library, persisted as a single YAML file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # --- queries -------------------------------------------------------- #
    def all(self) -> dict[str, Any]:
        """The full library as a ``{name: {description, fields}}`` mapping."""
        if not self.path.exists():
            return {}
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise TypeSchemaError("Type library file is corrupt (expected a mapping)")
        return data

    def get(self, name: str) -> dict[str, Any]:
        library = self.all()
        if name not in library:
            raise KeyError(name)
        return library[name]

    # --- mutations ------------------------------------------------------ #
    def upsert(self, name: str, type_def: dict[str, Any]) -> dict[str, Any]:
        """Add or replace one type, validating the resulting whole library."""
        name = (name or "").strip()
        if not _NAME_RE.fullmatch(name):
            raise TypeSchemaError(
                "Type name must start with a letter or underscore and use only letters, digits, underscores"
            )
        if not isinstance(type_def, dict):
            raise TypeSchemaError(f"Type '{name}' must be a mapping")
        library = self.all()
        candidate = dict(library)
        candidate[name] = {
            "description": str(type_def.get("description", "") or ""),
            "fields": type_def.get("fields") or {},
        }
        validate_library(candidate)
        self._write(candidate)
        return candidate[name]

    def delete(self, name: str) -> None:
        library = self.all()
        if name not in library:
            raise KeyError(name)
        remaining = {key: value for key, value in library.items() if key != name}
        # Re-validate so we never strand a reference to the deleted type.
        validate_library(remaining)
        self._write(remaining)

    def _write(self, library: dict[str, Any]) -> None:
        self.path.write_text(yaml.safe_dump(library, sort_keys=True), encoding="utf-8")
