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
        paths = [*self.root.glob("*.yaml"), *self.root.glob("*.yml")]
        return sorted(paths)

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
