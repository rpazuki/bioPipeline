from pathlib import Path

import pytest

from bio_pipeline_manager.yaml_store import YamlStore


VALID_YAML = """
pipelines:
  - demo:
      Inputs: []
      Processes: []
      Outputs: []
"""


def test_save_and_list_yaml(tmp_path: Path):
    store = YamlStore(tmp_path)

    path = store.save("demo", VALID_YAML)

    assert path.name == "demo.yaml"
    assert [p.name for p in store.list()] == ["demo.yaml"]
    assert store.pipeline_names("demo.yaml") == ["demo"]


def test_rejects_invalid_yaml(tmp_path: Path):
    store = YamlStore(tmp_path)

    with pytest.raises(ValueError):
        store.save("bad.yaml", "not: pipelines")


def test_rejects_path_traversal(tmp_path: Path):
    store = YamlStore(tmp_path)

    with pytest.raises(ValueError):
        store.save("../bad.yaml", VALID_YAML)

