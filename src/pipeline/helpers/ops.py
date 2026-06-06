"""Small, dependency-light process functions for YAML pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def ensure_list(value: Any) -> list[Any]:
    """Return value as a list so downstream steps can rely on list semantics."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def sequence(start: int, stop: int, step: int = 1) -> list[int]:
    """Build an integer sequence for synthetic or test payload generation."""
    return list(range(start, stop, step))


def format_message(message: str, prefix: str = "", suffix: str = "") -> str:
    """Create a formatted message string for logs, labels, or text outputs."""
    return f"{prefix}{message}{suffix}"


def log_value(message: object, prefix: str = "") -> str:
    """Print a value to stdout and return the rendered text."""
    rendered = f"{prefix}{message}"
    print(rendered, flush=True)
    return rendered


def save_text(text: str, path: str, append: bool = False, encoding: str = "utf-8") -> str:
    """Write text to disk and return the resolved file path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with target.open(mode, encoding=encoding) as handle:
        handle.write(text)
    return str(target.resolve())
