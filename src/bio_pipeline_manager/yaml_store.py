from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from bio_pipeline_manager.yaml_validation import ValidationReport, validate_labutils_yaml


class YamlStore:
    """Filesystem-backed storage for labUtils pipeline YAML files."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[Path]:
        paths = [*self.root.rglob("*.yaml"), *self.root.rglob("*.yml")]
        return sorted(paths)

    def list_folders(self) -> list[Path]:
        return sorted([path for path in self.root.rglob("*") if path.is_dir()])

    def load(self, name: str) -> str:
        path = self.resolve_name(name)
        return path.read_text(encoding="utf-8")

    def save(self, name: str, content: str, *, overwrite: bool = False) -> Path:
        self.validate_content(content)
        path = self.resolve_name(name)
        if path.exists() and not overwrite:
            raise FileExistsError(f"YAML already exists: {path}")
        path.write_text(content, encoding="utf-8")
        return path

    def pipeline_names(self, name: str) -> list[str]:
        data = self.parse(self.load(name))
        return [next(iter(item.keys())) for item in data["pipelines"]]

    def validate(self, name: str, *, validate_imports: bool = False) -> ValidationReport:
        return validate_labutils_yaml(self.load(name), validate_imports=validate_imports)

    def relative_name(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def create_folder(self, folder: str) -> Path:
        path = self.resolve_folder(folder)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def delete_file(self, name: str) -> None:
        path = self.resolve_name(name)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"YAML file not found: {name}")
        path.unlink()

    def move_file(self, source_name: str, destination_name: str, *, overwrite: bool = False) -> Path:
        source_path = self.resolve_name(source_name)
        destination_path = self.resolve_name(destination_name)
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"YAML file not found: {source_name}")
        if destination_path.exists() and source_path.resolve() != destination_path.resolve() and not overwrite:
            raise FileExistsError(f"YAML already exists: {destination_path}")
        if source_path.resolve() == destination_path.resolve():
            return source_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.replace(destination_path)
        self._cleanup_empty_parents(source_path.parent)
        return destination_path

    def delete_folder(self, folder: str) -> None:
        path = self.resolve_folder(folder)
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"Folder not found: {folder}")
        if any(path.iterdir()):
            raise ValueError(f"Folder is not empty: {folder}")
        path.rmdir()

    def resolve_folder(self, folder: str) -> Path:
        candidate = Path(folder)
        if str(candidate) in {"", "."}:
            return self.root.resolve()
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("Folder path must be relative and stay inside the YAML store")
        path = (self.root / candidate).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("Folder path resolves outside the YAML store")
        return path

    def resolve_name(self, name: str) -> Path:
        candidate = Path(name)
        if candidate.suffix not in {".yaml", ".yml"}:
            candidate = candidate.with_suffix(".yaml")
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("YAML name must be relative and stay inside the YAML store")
        path = (self.root / candidate).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("YAML name resolves outside the YAML store")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _cleanup_empty_parents(self, path: Path) -> None:
        root = self.root.resolve()
        current = path.resolve()
        while current != root:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    @staticmethod
    def parse(content: str) -> dict[str, Any]:
        report = validate_labutils_yaml(content)
        errors = [issue for issue in report.issues if issue.level == "error"]
        if errors:
            raise ValueError(errors[0].message)
        data = yaml.safe_load(content)
        return data

    @classmethod
    def validate_content(cls, content: str) -> None:
        cls.parse(content)
