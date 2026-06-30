import io
import json
import zipfile
from pathlib import Path

import pytest

from bio_pipeline_manager.backup import (
    BackupError,
    build_backup,
    build_requirements,
    import_backup,
)
from bio_pipeline_manager.job_definition_store import JobDefinitionStore
from bio_pipeline_manager.packages import InstallStore, PackageManager
from bio_pipeline_manager.published_jobs import PublishedJobStore
from bio_pipeline_manager.type_library_store import TypeLibraryStore
from bio_pipeline_manager.yaml_store import YamlStore

PIPELINE = """
pipelines:
  - demo:
      Inputs: []
      Processes: []
      Outputs: []
"""

JOB_DEF = """
job: growth_full
stages:
  - name: only
    pipeline_yaml: p.yaml
    pipeline: demo
    fanout: {type: none}
    output_dir: /out
"""

FIELDS = [
    {
        "id": "f1",
        "label": "F1",
        "type": "string",
        "bindings": [{"target": "definition_path", "path": ["defaults", "x"]}],
    }
]


def _fake_runner(code: int = 0, out: str = "ok", err: str = ""):
    def runner(python_executable: str, args: list[str]):
        runner.calls.append((python_executable, args))
        return code, out, err

    runner.calls = []
    return runner


class Stores:
    """The five stores a backup touches, on an isolated root."""

    def __init__(self, root: Path, runner=None):
        self.runner = runner or _fake_runner()
        self.yaml_store = YamlStore(root / "yamls")
        self.definition_store = JobDefinitionStore(root / "job_defs", root / "job_defs_archive")
        self.published_jobs = PublishedJobStore(root / "state.sqlite")
        self.packages = PackageManager(InstallStore(root / "installs.sqlite"), pip_runner=self.runner)
        self.type_library = TypeLibraryStore(root / "type_library.yaml")

    def as_kwargs(self) -> dict:
        return {
            "yaml_store": self.yaml_store,
            "definition_store": self.definition_store,
            "published_jobs": self.published_jobs,
            "packages": self.packages,
            "type_library": self.type_library,
        }


def _seed(stores: Stores) -> None:
    stores.yaml_store.save("demo.yaml", PIPELINE)
    stores.definition_store.save("job1.yaml", JOB_DEF)
    stores.published_jobs.create(
        name="Pub A",
        description="original",
        definition_name="job1.yaml",
        definition_content=JOB_DEF,
        fields=FIELDS,
        actor="admin",
        status="published",
    )
    stores.type_library.upsert("Sample", {"description": "", "type": "string"})
    stores.packages.install("pytest", source_type="pypi", actor="admin")


def _make_zip(files: dict[str, str], *, format_version: int = 1, with_manifest: bool = True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
        if with_manifest and "manifest.json" not in files:
            archive.writestr("manifest.json", json.dumps({"format_version": format_version, "contents": {}}))
    return buffer.getvalue()


def test_export_import_round_trip(tmp_path: Path):
    src = Stores(tmp_path / "src")
    _seed(src)
    data = build_backup(**src.as_kwargs(), created_by="admin")

    # The archive is a well-formed zip with the expected members.
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
    assert {"manifest.json", "pipelines/demo.yaml", "job_definitions/job1.yaml",
            "type_library.yaml", "requirements.txt"} <= names
    assert any(n.startswith("published_jobs/") and n.endswith(".json") for n in names)

    dst = Stores(tmp_path / "dst")
    report = import_backup(data, **dst.as_kwargs(), overwrite=False, install_packages=True, actor="admin2")

    assert report.pipelines.created == ["demo.yaml"]
    assert report.job_definitions.created == ["job1.yaml"]
    assert report.published_jobs.created == ["Pub A"]
    assert report.type_library.created == ["Sample"]
    assert report.packages["attempted"] and report.packages["ok"]

    # Content actually landed in the destination stores.
    assert dst.yaml_store.load("demo.yaml") == src.yaml_store.load("demo.yaml")
    assert dst.definition_store.load("job1.yaml") == JOB_DEF
    imported = {r.name: r for r in dst.published_jobs.list()}
    assert "Pub A" in imported and imported["Pub A"].status == "published"
    assert imported["Pub A"].definition_content == JOB_DEF
    assert "Sample" in dst.type_library.all()
    # requirements were fed through the install mechanism (pip -r <tempfile>).
    assert dst.runner.calls and dst.runner.calls[-1][1][:2] == ["install", "-r"]


def test_overwrite_false_skips_existing(tmp_path: Path):
    src = Stores(tmp_path / "src")
    _seed(src)
    data = build_backup(**src.as_kwargs(), created_by="admin")

    dst = Stores(tmp_path / "dst")
    import_backup(data, **dst.as_kwargs(), overwrite=False, install_packages=False, actor="a")
    report = import_backup(data, **dst.as_kwargs(), overwrite=False, install_packages=False, actor="a")

    assert report.pipelines.skipped == ["demo.yaml"]
    assert report.job_definitions.skipped == ["job1.yaml"]
    assert report.published_jobs.skipped == ["Pub A"]
    assert report.type_library.skipped == ["Sample"]
    assert report.pipelines.created == []


def test_overwrite_true_replaces_existing(tmp_path: Path):
    src = Stores(tmp_path / "src")
    _seed(src)
    data = build_backup(**src.as_kwargs(), created_by="admin")

    dst = Stores(tmp_path / "dst")
    import_backup(data, **dst.as_kwargs(), overwrite=False, install_packages=False, actor="a")
    # Mutate the destination so we can prove overwrite restores the backup content.
    dst.yaml_store.save("demo.yaml", "pipelines:\n  - other:\n      Inputs: []\n      Processes: []\n      Outputs: []\n", overwrite=True)

    report = import_backup(data, **dst.as_kwargs(), overwrite=True, install_packages=False, actor="a")

    assert report.pipelines.overwritten == ["demo.yaml"]
    assert report.job_definitions.overwritten == ["job1.yaml"]
    assert report.published_jobs.overwritten == ["Pub A"]
    assert report.type_library.overwritten == ["Sample"]
    assert dst.yaml_store.load("demo.yaml") == src.yaml_store.load("demo.yaml")


def test_published_job_matched_by_name(tmp_path: Path):
    src = Stores(tmp_path / "src")
    src.definition_store.save("job1.yaml", JOB_DEF)
    src.published_jobs.create(
        name="Pub A", description="from-backup", definition_name="job1.yaml",
        definition_content=JOB_DEF, fields=FIELDS, actor="admin", status="published",
    )
    data = build_backup(**src.as_kwargs(), created_by="admin")

    dst = Stores(tmp_path / "dst")
    dst.published_jobs.create(
        name="Pub A", description="pre-existing", definition_name="x",
        definition_content=JOB_DEF, fields=FIELDS, actor="local", status="draft",
    )

    skip = import_backup(data, **dst.as_kwargs(), overwrite=False, install_packages=False, actor="a")
    assert skip.published_jobs.skipped == ["Pub A"]
    assert {r.name for r in dst.published_jobs.list()} == {"Pub A"}
    assert dst.published_jobs.list()[0].description == "pre-existing"

    over = import_backup(data, **dst.as_kwargs(), overwrite=True, install_packages=False, actor="a")
    assert over.published_jobs.overwritten == ["Pub A"]
    matched = [r for r in dst.published_jobs.list() if r.name == "Pub A"]
    assert len(matched) == 1 and matched[0].description == "from-backup"


def test_build_requirements_net_set(tmp_path: Path):
    manager = PackageManager(InstallStore(tmp_path / "installs.sqlite"), pip_runner=_fake_runner())
    manager.install("pytest", source_type="pypi", actor="a")
    manager.install("addict", source_type="pypi", actor="a")
    manager.uninstall("addict", actor="a")  # net: addict removed
    manager.install("name @ git+https://example/x.git", source_type="git", actor="a")
    manager.install("/local/path", source_type="editable", actor="a")
    manager.pip_runner = _fake_runner(1, "", "boom")
    manager.install("ghost-pkg", source_type="pypi", actor="a")  # failed -> excluded

    text = build_requirements(manager)
    lines = [line for line in text.splitlines() if line.strip()]

    assert any(line.startswith("pytest==") for line in lines)
    assert not any(line.lstrip("# ").startswith("addict") for line in lines)
    assert "name @ git+https://example/x.git" in lines
    assert any(line.startswith("# editable install") for line in lines)
    assert not any(line.startswith("ghost-pkg") for line in lines)


def test_install_packages_flag_off(tmp_path: Path):
    src = Stores(tmp_path / "src")
    _seed(src)
    data = build_backup(**src.as_kwargs(), created_by="admin")

    dst = Stores(tmp_path / "dst")
    report = import_backup(data, **dst.as_kwargs(), overwrite=False, install_packages=False, actor="a")

    assert report.packages["attempted"] is False
    assert dst.runner.calls == []  # pip never invoked


def test_import_rejects_non_zip(tmp_path: Path):
    dst = Stores(tmp_path / "dst")
    with pytest.raises(BackupError):
        import_backup(b"definitely not a zip", **dst.as_kwargs(), overwrite=False, install_packages=False, actor="a")


def test_import_rejects_unknown_format_version(tmp_path: Path):
    dst = Stores(tmp_path / "dst")
    blob = _make_zip({}, format_version=999)
    with pytest.raises(BackupError):
        import_backup(blob, **dst.as_kwargs(), overwrite=False, install_packages=False, actor="a")


def test_import_missing_manifest_rejected(tmp_path: Path):
    dst = Stores(tmp_path / "dst")
    blob = _make_zip({"pipelines/demo.yaml": PIPELINE}, with_manifest=False)
    with pytest.raises(BackupError):
        import_backup(blob, **dst.as_kwargs(), overwrite=False, install_packages=False, actor="a")


def test_invalid_content_recorded_as_per_item_error(tmp_path: Path):
    dst = Stores(tmp_path / "dst")
    blob = _make_zip({"pipelines/bad.yaml": "not: pipelines", "pipelines/demo.yaml": PIPELINE})
    report = import_backup(blob, **dst.as_kwargs(), overwrite=False, install_packages=False, actor="a")

    assert "demo.yaml" in report.pipelines.created
    assert [e["name"] for e in report.pipelines.errors] == ["bad.yaml"]
