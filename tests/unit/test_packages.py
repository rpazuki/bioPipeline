from pathlib import Path

import pytest

from bio_pipeline_manager.packages import (
    InstallStore,
    PackageBusyError,
    PackageError,
    PackageManager,
    distribution_name,
)


def _fake_runner(code: int = 0, out: str = "ok", err: str = ""):
    def runner(python_executable: str, args: list[str]):
        runner.calls.append((python_executable, args))
        return code, out, err

    runner.calls = []
    return runner


def _manager(tmp_path: Path, runner=None, job_guard=None) -> PackageManager:
    return PackageManager(
        InstallStore(tmp_path / "installs.sqlite"),
        pip_runner=runner or _fake_runner(),
        job_guard=job_guard,
    )


def test_install_records_audit_and_resolves_version(tmp_path: Path):
    runner = _fake_runner(0)
    manager = _manager(tmp_path, runner)

    # `pytest` is already installed, so the version resolves without a real install.
    result = manager.install("pytest", source_type="pypi", actor="tester")

    assert result.ok and result.action == "install"
    assert result.resolved_version is not None
    assert runner.calls[0][1] == ["install", "pytest"]

    history = manager.store.history()
    assert len(history) == 1
    assert history[0]["actor"] == "tester"
    assert history[0]["ok"] is True
    assert history[0]["spec"] == "pytest"


def test_install_failure_is_recorded_without_version(tmp_path: Path):
    manager = _manager(tmp_path, _fake_runner(1, "", "could not find package"))
    result = manager.install("nonexistent-xyz", source_type="pypi")

    assert not result.ok
    assert result.exit_code == 1
    assert result.resolved_version is None
    assert manager.store.history()[0]["ok"] is False


def test_editable_install_uses_e_flag(tmp_path: Path):
    runner = _fake_runner(0)
    _manager(tmp_path, runner).install("/path/to/src", source_type="editable")
    assert runner.calls[0][1] == ["install", "-e", "/path/to/src"]


def test_requirements_install_uses_r_flag(tmp_path: Path):
    runner = _fake_runner(0)
    _manager(tmp_path, runner).install("reqs.txt", source_type="requirements")
    assert runner.calls[0][1] == ["install", "-r", "reqs.txt"]


def test_uninstall_uses_yes_flag(tmp_path: Path):
    runner = _fake_runner(0)
    result = _manager(tmp_path, runner).uninstall("addict")
    assert runner.calls[0][1] == ["uninstall", "-y", "addict"]
    assert result.action == "uninstall"


def test_busy_guard_blocks_changes(tmp_path: Path):
    runner = _fake_runner(0)
    manager = _manager(tmp_path, runner, job_guard=lambda: True)
    with pytest.raises(PackageBusyError):
        manager.install("pytest")
    with pytest.raises(PackageBusyError):
        manager.uninstall("pytest")
    assert runner.calls == []  # pip never invoked


def test_unsupported_source_type_raises(tmp_path: Path):
    with pytest.raises(PackageError):
        _manager(tmp_path).install("x", source_type="moonbeam")


def test_empty_spec_raises(tmp_path: Path):
    with pytest.raises(PackageError):
        _manager(tmp_path).install("   ", source_type="pypi")


def test_list_installed_includes_known_package(tmp_path: Path):
    names = {pkg["name"].lower() for pkg in _manager(tmp_path).list_installed()}
    assert "pytest" in names


def test_list_installed_has_no_duplicate_names(tmp_path: Path):
    # importlib.metadata can repeat a name (editable install + egg-info); the
    # manager must dedupe so the UI never renders duplicate React keys.
    installed = _manager(tmp_path).list_installed()
    names = [pkg["name"].lower() for pkg in installed]
    assert len(names) == len(set(names))


@pytest.mark.parametrize(
    "spec, source_type, expected",
    [
        ("addict", "pypi", "addict"),
        ("labUtils==1.2.0", "pypi", "labUtils"),
        ("pandas[extra]", "pypi", "pandas"),
        ("name @ git+https://example/x.git", "git", "name"),
        ("git+https://example/x.git#egg=foo", "git", "foo"),
        ("/some/local/path", "editable", None),
        ("requirements.txt", "requirements", None),
    ],
)
def test_distribution_name(spec, source_type, expected):
    assert distribution_name(spec, source_type) == expected
