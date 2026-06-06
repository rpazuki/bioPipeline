"""Data-discovery helpers for pipeline fan-out.

Transferred from the external ``labUtils`` package alongside the engine. These
back the fan-out strategies of a Job Definition (``mapping_file``, ``patterns``,
``folders``).
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pandas as pd
import yaml

log = logging.getLogger(__name__)


def list_folders(path: str | Path) -> list[Path]:
    """Return the immediate sub-directories of ``path``."""
    path = Path(path)
    return [p for p in path.iterdir() if p.is_dir()]


def read_csv(path: str | Path) -> pd.DataFrame:
    """Read a CSV file into a DataFrame (importable from YAML as a process)."""
    return pd.read_csv(Path(path))


def load_file_mapping(file_path: str | Path) -> dict:
    """Load a file mapping from CSV, YAML, or a Python/literal dict file.

    Returns a dict mapping raw-data file -> metadata file (the convention used
    by the preprocessing fan-out).
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Mapping file not found: {file_path}")

    suffix = file_path.suffix.lower()

    if suffix == ".csv":
        df = pd.read_csv(file_path)
        if len(df.columns) != 2:
            raise ValueError("CSV file must have exactly 2 columns (metadata_file, raw_data_file)")
        return dict(zip(df.iloc[:, 0], df.iloc[:, 1]))  # noqa: B905

    elif suffix in [".yaml", ".yml"]:
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError("YAML file must contain a dictionary")
        return data

    elif suffix == ".py":
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
        try:
            tree = ast.parse(content)
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id in ["file_pars", "file_mapping", "mapping"]:
                            return ast.literal_eval(node.value)
            return ast.literal_eval(content.strip())
        except (ValueError, SyntaxError) as e:
            raise ValueError(f"Could not parse Python dictionary from file: {e}") from e

    else:
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read().strip()
            return ast.literal_eval(content)
        except (ValueError, SyntaxError) as e:
            raise ValueError(f"Unsupported file format or invalid content: {e}") from e


def create_file_mapping_from_patterns(data_dir: str | Path, raw_pattern: str, meta_pattern: str) -> dict:
    """Pair raw and metadata files matched by glob patterns, in sorted order.

    Returns a dict mapping raw-data file name -> metadata file name.
    """
    data_dir = Path(data_dir)

    raw_data_files = sorted(data_dir.glob(raw_pattern))
    meta_data_files = sorted(data_dir.glob(meta_pattern))

    if not raw_data_files:
        raise ValueError(f"No raw data files found matching pattern: {raw_pattern}")
    if not meta_data_files:
        raise ValueError(f"No metadata files found matching pattern: {meta_pattern}")

    if len(raw_data_files) != len(meta_data_files):
        log.warning("Found %s raw data files but %s metadata files", len(raw_data_files), len(meta_data_files))
        log.warning("Files will be paired in order, remaining files will be skipped")

    file_mapping = {}
    min_length = min(len(raw_data_files), len(meta_data_files))
    for i in range(min_length):
        file_mapping[raw_data_files[i].name] = meta_data_files[i].name

    return file_mapping
