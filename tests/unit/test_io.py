"""Tests for the transferred data-discovery helpers (pipeline/io.py)."""

from pathlib import Path

import pandas as pd
import pytest

from pipeline.io import (
    create_file_mapping_from_patterns,
    list_folders,
    load_file_mapping,
    read_csv,
)


# --------------------------------------------------------------------------- #
# load_file_mapping
# --------------------------------------------------------------------------- #
def test_load_mapping_yaml(tmp_path: Path):
    f = tmp_path / "m.yaml"
    f.write_text("raw1.csv: meta1.csv\nraw2.csv: meta2.csv\n", encoding="utf-8")
    assert load_file_mapping(f) == {"raw1.csv": "meta1.csv", "raw2.csv": "meta2.csv"}


def test_load_mapping_csv(tmp_path: Path):
    f = tmp_path / "m.csv"
    pd.DataFrame({"raw": ["r1.csv", "r2.csv"], "meta": ["m1.csv", "m2.csv"]}).to_csv(f, index=False)
    assert load_file_mapping(f) == {"r1.csv": "m1.csv", "r2.csv": "m2.csv"}


def test_load_mapping_csv_wrong_columns_raises(tmp_path: Path):
    f = tmp_path / "m.csv"
    pd.DataFrame({"a": [1], "b": [2], "c": [3]}).to_csv(f, index=False)
    with pytest.raises(ValueError, match="exactly 2 columns"):
        load_file_mapping(f)


def test_load_mapping_py_file_pars(tmp_path: Path):
    f = tmp_path / "m.py"
    f.write_text("file_pars = {'r1.csv': 'm1.csv'}\n", encoding="utf-8")
    assert load_file_mapping(f) == {"r1.csv": "m1.csv"}


def test_load_mapping_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_file_mapping(tmp_path / "nope.yaml")


def test_load_mapping_yaml_non_dict_raises(tmp_path: Path):
    f = tmp_path / "m.yaml"
    f.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dictionary"):
        load_file_mapping(f)


def test_load_mapping_unknown_extension_literal(tmp_path: Path):
    f = tmp_path / "m.txt"
    f.write_text("{'r1.csv': 'm1.csv'}", encoding="utf-8")
    assert load_file_mapping(f) == {"r1.csv": "m1.csv"}


def test_load_mapping_unknown_extension_invalid_raises(tmp_path: Path):
    f = tmp_path / "m.txt"
    f.write_text("not a dict literal", encoding="utf-8")
    with pytest.raises(ValueError):
        load_file_mapping(f)


# --------------------------------------------------------------------------- #
# create_file_mapping_from_patterns
# --------------------------------------------------------------------------- #
def test_patterns_pairs_sorted(tmp_path: Path):
    for name in ["raw2.csv", "raw1.csv", "meta2.csv", "meta1.csv"]:
        (tmp_path / name).write_text("x", encoding="utf-8")

    mapping = create_file_mapping_from_patterns(tmp_path, "raw*.csv", "meta*.csv")

    assert mapping == {"raw1.csv": "meta1.csv", "raw2.csv": "meta2.csv"}


def test_patterns_no_raw_match_raises(tmp_path: Path):
    (tmp_path / "meta1.csv").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="No raw data files"):
        create_file_mapping_from_patterns(tmp_path, "raw*.csv", "meta*.csv")


def test_patterns_no_meta_match_raises(tmp_path: Path):
    (tmp_path / "raw1.csv").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="No metadata files"):
        create_file_mapping_from_patterns(tmp_path, "raw*.csv", "meta*.csv")


def test_patterns_mismatched_counts_pairs_min(tmp_path: Path):
    for name in ["raw1.csv", "raw2.csv", "raw3.csv", "meta1.csv"]:
        (tmp_path / name).write_text("x", encoding="utf-8")
    mapping = create_file_mapping_from_patterns(tmp_path, "raw*.csv", "meta*.csv")
    assert mapping == {"raw1.csv": "meta1.csv"}


def test_patterns_excludes_metadata_from_broad_raw_pattern(tmp_path: Path):
    # The raw pattern (*.csv) also matches the metadata files (*_meta.csv); those must
    # be excluded from the data files, not paired as data. Otherwise sorted pairing
    # produces nonsense like a_meta.csv -> b_meta.csv and drops real data files.
    for name in ["a.csv", "b.csv", "a_meta.csv", "b_meta.csv"]:
        (tmp_path / name).write_text("x", encoding="utf-8")

    mapping = create_file_mapping_from_patterns(tmp_path, "*.csv", "*_meta.csv")

    assert mapping == {"a.csv": "a_meta.csv", "b.csv": "b_meta.csv"}


def test_patterns_only_metadata_present_raises_no_raw(tmp_path: Path):
    # If everything matching the broad raw pattern is actually metadata, there are no
    # real data files — surface that rather than pairing metadata with itself.
    for name in ["a_meta.csv", "b_meta.csv"]:
        (tmp_path / name).write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="No raw data files"):
        create_file_mapping_from_patterns(tmp_path, "*.csv", "*_meta.csv")


# --------------------------------------------------------------------------- #
# list_folders / read_csv
# --------------------------------------------------------------------------- #
def test_list_folders_returns_only_dirs(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    names = {p.name for p in list_folders(tmp_path)}
    assert names == {"a", "b"}


def test_read_csv(tmp_path: Path):
    f = tmp_path / "d.csv"
    pd.DataFrame({"a": [1, 2]}).to_csv(f, index=False)
    assert list(read_csv(f)["a"]) == [1, 2]
