"""Read-only introspection of installed packages (functions/classes/signatures)."""

from __future__ import annotations

import pytest

from bio_pipeline_manager.package_introspect import (
    PackageIntrospectError,
    get_signature,
    inspect_module,
    search_members,
)

# --- Fixtures defined in this module so introspecting __name__ has real members. --- #


def sample_add(a: int, b: int = 1) -> int:
    """Add two numbers.

    Second paragraph is dropped from the one-line summary.
    """
    return a + b


def _private_helper() -> None:  # underscore-prefixed: excluded from listings
    return None


class SampleWidget:
    """A sample widget."""

    def spin(self, turns: int = 3) -> str:
        """Spin the widget."""
        return "spun" * turns

    def _internal(self) -> None:  # excluded: private
        return None


def test_inspect_module_lists_functions_and_classes():
    result = inspect_module(__name__)
    assert result["module"] == __name__
    function_names = {item["name"] for item in result["functions"]}
    class_names = {item["name"] for item in result["classes"]}
    assert "sample_add" in function_names
    assert "SampleWidget" in class_names
    # Private members and re-imported names (e.g. pytest) are excluded.
    assert "_private_helper" not in function_names
    assert "pytest" not in class_names and "pytest" not in function_names
    add = next(item for item in result["functions"] if item["name"] == "sample_add")
    assert add["signature"] == "(a: int, b: int = 1) -> int"
    assert add["summary"] == "Add two numbers."
    assert add["qualified_name"] == f"{__name__}.sample_add"


def test_search_members_by_name_within_module():
    result = search_members("widget", module=__name__)
    names = {item["name"] for item in result["matches"]}
    assert "SampleWidget" in names
    assert result["truncated"] is False
    # A query that matches nothing returns an empty (not error) result.
    assert search_members("zzz_no_such_member", module=__name__)["matches"] == []


def test_get_signature_of_function_reports_parameters():
    result = get_signature(f"{__name__}.sample_add")
    assert result["kind"] == "function"
    assert result["signature"] == "sample_add(a: int, b: int = 1) -> int"
    assert result["returns"] == "int"
    params = {param["name"]: param for param in result["parameters"]}
    assert params["a"]["default"] is None
    assert params["b"]["default"] == "1"
    assert params["b"]["annotation"] == "int"
    assert result["doc"].startswith("Add two numbers.")


def test_get_signature_of_class_lists_public_methods():
    result = get_signature(f"{__name__}.SampleWidget")
    assert result["kind"] == "class"
    method_names = {method["name"] for method in result["methods"]}
    assert "spin" in method_names
    assert "_internal" not in method_names


def test_get_signature_handles_builtins_without_a_signature():
    # Many C builtins expose no introspectable signature — that degrades to an
    # empty signature string, it does not raise.
    result = get_signature("math.sqrt")
    assert result["kind"] == "function"
    assert result["name"] == "sqrt"


def test_search_without_module_scans_loaded_modules():
    # No module ⇒ scan already-imported modules; this test module is imported, so
    # its own members are reachable without triggering new imports.
    result = search_members("SampleWidget")
    assert any(match["name"] == "SampleWidget" for match in result["matches"])


def test_inspect_real_labutils_module():
    result = inspect_module("labUtils.media_bot")
    assert result["module"] == "labUtils.media_bot"
    # CustomReplicateRule is a TypedDict defined there — it lists as a class.
    assert any(item["name"] == "CustomReplicateRule" for item in result["classes"])


def test_errors_are_controlled():
    with pytest.raises(PackageIntrospectError):
        inspect_module("no_such_module_xyz")
    with pytest.raises(PackageIntrospectError, match="not a function or class"):
        get_signature("math.pi")  # a float, not callable
    with pytest.raises(PackageIntrospectError):
        get_signature("just_a_bare_name")
    with pytest.raises(PackageIntrospectError, match="non-empty search query"):
        search_members("   ")
