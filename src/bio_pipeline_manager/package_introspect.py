"""Introspect installed packages: list functions/classes, search them, read signatures.

Lets an agent (via the MCP server) or the API *explore what is importable* in the
backend's Python environment — which functions and classes a module exposes, search
for them by name, and read a function's (or class's) signature and docstring —
**without executing** any of them. It is the read-only companion to
:mod:`bio_pipeline_manager.packages` (which installs/uninstalls) and to
:mod:`bio_pipeline_manager.type_extract` (which turns a *class* into a type-library
entry): here the goal is discovery, so an admin authoring a pipeline can find the
right ``labUtils.*`` process function and confirm its parameters.

Three operations:

- :func:`inspect_module` — the public functions and classes a module exposes
  (honouring ``__all__`` when present, else filtering to members *defined here*),
  plus its immediate submodules.
- :func:`search_members` — case-insensitive name search across a package's
  submodules (or, with no module, the already-imported modules), bounded and
  fail-soft so a broken submodule never aborts the search.
- :func:`get_signature` — the resolved signature, docstring, and parameter list of
  one function or class (a class also lists its public methods).

Importing a module runs its top-level code — the same trade-off
:func:`bio_pipeline_manager.type_extract.extract_type` already makes — so these are
exposed admin-only.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
import types
from typing import Any

# Ceiling on how many modules a single search will import/scan, so walking a large
# package (or the whole loaded module table) stays bounded. A hit past the cap sets
# ``truncated`` in the result rather than running unbounded.
_SEARCH_MODULE_CAP = 600


class PackageIntrospectError(ValueError):
    """Raised when a module/name cannot be imported or is the wrong kind of object."""


# --------------------------------------------------------------------------- #
# Module inspection
# --------------------------------------------------------------------------- #
def inspect_module(module_name: str) -> dict[str, Any]:
    """Return the public functions and classes ``module_name`` exposes.

    Result: ``{module, doc, functions: [...], classes: [...], submodules: [...]}``.
    Each member carries ``name``, ``qualified_name``, ``kind``, ``summary`` (first
    doc line) and a best-effort ``signature``.
    """
    module = _import_module(module_name)
    functions: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    exported = _exported_names(module)
    for name, obj in _safe_members(module):
        if name.startswith("_"):
            continue
        kind = _member_kind(obj)
        if kind is None:
            continue
        if not _belongs(obj, module.__name__, exported, name):
            continue
        info = _member_info(name, obj, module.__name__, kind)
        (classes if kind == "class" else functions).append(info)
    functions.sort(key=lambda item: item["name"].lower())
    classes.sort(key=lambda item: item["name"].lower())
    return {
        "module": module.__name__,
        "doc": _first_doc(module),
        "functions": functions,
        "classes": classes,
        "submodules": _submodules(module),
    }


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
def search_members(query: str, *, module: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Case-insensitive search for functions/classes whose name matches ``query``.

    With ``module`` set, walks that package and its submodules (bounded, importing
    each — a submodule that fails to import is skipped). With no ``module``, scans
    the already-imported modules (no new imports). Returns
    ``{matches, searched_modules, truncated}``; ``truncated`` is true if the module
    cap or the match ``limit`` cut the walk short.
    """
    needle = (query or "").strip().lower()
    if not needle:
        raise PackageIntrospectError("A non-empty search query is required")
    limit = max(1, min(int(limit or 50), 200))
    modules, truncated = _modules_to_search(module)
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mod in modules:
        mod_name = getattr(mod, "__name__", "") or ""
        exported = _exported_names(mod)
        for name, obj in _safe_members(mod):
            if name.startswith("_"):
                continue
            kind = _member_kind(obj)
            if kind is None or not _belongs(obj, mod_name, exported, name):
                continue
            info = _member_info(name, obj, mod_name, kind)
            if needle not in info["name"].lower() and needle not in info["qualified_name"].lower():
                continue
            if info["qualified_name"] in seen:
                continue
            seen.add(info["qualified_name"])
            matches.append(info)
            if len(matches) >= limit:
                return {"matches": matches, "searched_modules": len(modules), "truncated": True}
    matches.sort(key=lambda item: item["qualified_name"].lower())
    return {"matches": matches, "searched_modules": len(modules), "truncated": truncated}


# --------------------------------------------------------------------------- #
# Signature
# --------------------------------------------------------------------------- #
def get_signature(qualified_name: str) -> dict[str, Any]:
    """Return the signature, docstring and parameters of a function or class.

    ``qualified_name`` is ``module.sub.name`` (module prefixes are tried longest
    first, so a nested attribute like ``pkg.mod.Class.method`` resolves too). A
    class reports its constructor signature plus a list of its public methods.
    """
    obj = _resolve(qualified_name)
    if inspect.isclass(obj):
        kind = "class"
    elif inspect.isroutine(obj):
        kind = "function"
    else:
        raise PackageIntrospectError(
            f"'{qualified_name}' is a {type(obj).__name__}, not a function or class"
        )
    name = getattr(obj, "__name__", qualified_name.rsplit(".", 1)[-1])
    signature = _safe_signature(obj)
    result: dict[str, Any] = {
        "qualified_name": _qualified(obj) or qualified_name,
        "name": name,
        "kind": kind,
        "module": getattr(obj, "__module__", "") or "",
        "signature": f"{name}{signature}" if signature else "",
        "doc": inspect.getdoc(obj) or "",
        "parameters": _parameters(obj),
        "returns": _return_annotation(obj),
        "methods": _class_methods(obj) if kind == "class" else [],
    }
    return result


# --------------------------------------------------------------------------- #
# Member helpers
# --------------------------------------------------------------------------- #
def _member_kind(obj: Any) -> str | None:
    """``"class"`` / ``"function"`` for a class or any routine, else ``None``."""
    if inspect.isclass(obj):
        return "class"
    if inspect.isroutine(obj):  # function, builtin, method, method-wrapper
        return "function"
    return None


def _member_info(name: str, obj: Any, module_name: str, kind: str) -> dict[str, Any]:
    return {
        "name": name,
        "qualified_name": _qualified(obj) or f"{module_name}.{name}",
        "kind": kind,
        "summary": _first_doc(obj),
        "signature": _safe_signature(obj),
    }


def _class_methods(cls: Any) -> list[dict[str, Any]]:
    """Public methods declared on ``cls`` (dunders and privates excluded), capped."""
    methods: list[dict[str, Any]] = []
    module_name = getattr(cls, "__module__", "") or ""
    for name, obj in _safe_members(cls):
        if name.startswith("_") or not inspect.isroutine(obj):
            continue
        methods.append(_member_info(name, obj, module_name, "method"))
        if len(methods) >= 60:
            break
    methods.sort(key=lambda item: item["name"].lower())
    return methods


def _parameters(obj: Any) -> list[dict[str, Any]]:
    signature = _signature_of(obj)
    if signature is None:
        return []
    params: list[dict[str, Any]] = []
    for param in signature.parameters.values():
        params.append(
            {
                "name": param.name,
                "kind": param.kind.name.lower(),
                "default": None if param.default is inspect.Parameter.empty else repr(param.default),
                "annotation": "" if param.annotation is inspect.Parameter.empty else _label(param.annotation),
            }
        )
    return params


def _return_annotation(obj: Any) -> str:
    signature = _signature_of(obj)
    if signature is None or signature.return_annotation is inspect.Signature.empty:
        return ""
    return _label(signature.return_annotation)


def _safe_signature(obj: Any) -> str:
    signature = _signature_of(obj)
    return str(signature) if signature is not None else ""


def _signature_of(obj: Any) -> inspect.Signature | None:
    """Best-effort ``inspect.Signature``, resolving PEP 563 string annotations.

    Modules using ``from __future__ import annotations`` store annotations as
    strings, which render quoted (``b: 'int'``). ``eval_str=True`` turns them back
    into real types for clean output; if an annotation can't be resolved (a forward
    ref to a name not in scope), fall back to the raw string form rather than fail.
    """
    try:
        return inspect.signature(obj, eval_str=True)
    except (ValueError, TypeError):
        return None
    except Exception:  # noqa: BLE001 - unresolvable annotation eval; use the raw form
        try:
            return inspect.signature(obj)
        except (ValueError, TypeError):
            return None


# --------------------------------------------------------------------------- #
# Module walking / resolution
# --------------------------------------------------------------------------- #
def _modules_to_search(module_name: str | None) -> tuple[list[types.ModuleType], bool]:
    """The bounded list of modules a search scans, plus whether it was truncated."""
    if module_name:
        root = _import_module(module_name)
        modules: list[types.ModuleType] = []
        for mod in _walk_package(root):
            modules.append(mod)
            if len(modules) >= _SEARCH_MODULE_CAP:
                return modules, True
        return modules, False
    # No module given: scan every already-imported module — no new imports happen, so
    # this is bounded by what's loaded (the match limit caps the output) and needs no
    # module cap. Snapshot the values first: iterating sys.modules while a member access
    # lazily imports a submodule would otherwise mutate the dict mid-iteration.
    loaded = [mod for mod in list(sys.modules.values()) if isinstance(mod, types.ModuleType)]
    return loaded, False


def _walk_package(root: types.ModuleType):
    """Yield ``root`` then every importable submodule (failures skipped)."""
    yield root
    path = getattr(root, "__path__", None)
    if not path:
        return
    prefix = root.__name__ + "."
    try:
        walker = pkgutil.walk_packages(path, prefix, onerror=lambda _name: None)
    except Exception:  # noqa: BLE001 - a broken package tree must not abort the search
        return
    for info in walker:
        try:
            yield importlib.import_module(info.name)
        except Exception:  # noqa: BLE001 - a submodule that won't import is simply skipped
            continue


def _import_module(module_name: str) -> types.ModuleType:
    name = (module_name or "").strip()
    if not name:
        raise PackageIntrospectError("A module name is required")
    try:
        return importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - ImportError or a top-level side effect
        raise PackageIntrospectError(f"Could not import module '{name}': {exc}") from exc


def _resolve(qualified_name: str) -> Any:
    """Resolve ``module.sub.name`` to the object, trying module prefixes longest first."""
    parts = (qualified_name or "").strip().split(".")
    if len(parts) < 2 or not all(parts):
        raise PackageIntrospectError("Qualified name must look like 'module.name'")
    for split in range(len(parts) - 1, 0, -1):
        module_name = ".".join(parts[:split])
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        obj: Any = module
        for attr in parts[split:]:
            try:
                obj = getattr(obj, attr)
            except AttributeError as exc:
                raise PackageIntrospectError(
                    f"'{qualified_name}': '{attr}' not found in '{module_name}'"
                ) from exc
        return obj
    raise PackageIntrospectError(f"Could not import a module from '{qualified_name}'")


def _submodules(module: types.ModuleType) -> list[str]:
    """Immediate submodule names (enumerated without importing them)."""
    path = getattr(module, "__path__", None)
    if not path:
        return []
    names: list[str] = []
    try:
        for info in pkgutil.iter_modules(path):
            names.append(f"{module.__name__}.{info.name}")
    except Exception:  # noqa: BLE001 - namespace/partial packages
        return sorted(names)
    return sorted(names)


# --------------------------------------------------------------------------- #
# Small utilities
# --------------------------------------------------------------------------- #
def _exported_names(module: types.ModuleType) -> set[str] | None:
    """``__all__`` as a set (the module's own public API), or None if unset."""
    exported = getattr(module, "__all__", None)
    if isinstance(exported, (list, tuple, set)):
        return {str(name) for name in exported}
    return None


def _belongs(obj: Any, module_name: str, exported: set[str] | None, name: str) -> bool:
    """Whether a member counts as belonging to ``module_name``.

    With ``__all__`` present, membership is exactly that list. Otherwise a member
    belongs when it was *defined here* (its ``__module__`` is this module or a
    submodule) — which drops re-exported stdlib/third-party names from the listing.
    """
    if exported is not None:
        return name in exported
    obj_module = getattr(obj, "__module__", None)
    if not isinstance(obj_module, str):
        return False
    return obj_module == module_name or obj_module.startswith(module_name + ".")


def _safe_members(obj: Any) -> list[tuple[str, Any]]:
    try:
        return inspect.getmembers(obj)
    except Exception:  # noqa: BLE001 - a member whose access raises must not abort
        return []


def _first_doc(obj: Any) -> str:
    doc = (inspect.getdoc(obj) or "").strip()
    return doc.split("\n", 1)[0] if doc else ""


def _qualified(obj: Any) -> str:
    module = getattr(obj, "__module__", "") or ""
    qualname = getattr(obj, "__qualname__", None) or getattr(obj, "__name__", "") or ""
    if not qualname:
        return ""
    if not module or module in ("builtins", "__main__"):
        return qualname
    return f"{module}.{qualname}"


def _label(annotation: Any) -> str:
    return getattr(annotation, "__name__", None) or str(annotation)
