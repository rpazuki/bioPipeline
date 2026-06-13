"""Introspect a Python class into type-library entries.

Turns a ``TypedDict`` / dataclass / Pydantic model (e.g.
``labUtils.media_bot.CustomReplicateRule``) into the same ``{name: {description,
fields}}`` shape the type library stores. Nested structured types are emitted
recursively, so the result is self-contained and can be upserted as-is.

Type mapping (see ``docs/TYPED_DEFINITIONS.md`` §6):

- ``str`` -> string, ``int`` -> integer, ``float`` -> float, ``bool`` -> boolean
- ``Literal["a", "b"]`` -> enum with options
- ``X | None`` / ``Optional[X]`` -> underlying ``X`` with ``required: false``
- ``list[X]`` -> ``X`` with ``container: list``; ``dict[str, X]`` -> ``container: map``
- nested ``TypedDict`` / dataclass / Pydantic model -> a nested named type
- anything else -> ``string`` (with a warning)
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import types as _types
import typing
from typing import Any, get_args, get_origin

from bio_pipeline_manager.type_schema import validate_library

_PRIMITIVES: dict[type, str] = {str: "string", int: "integer", float: "float", bool: "boolean"}
_NONE_TYPE = type(None)


class TypeExtractError(ValueError):
    """Raised when a qualified name cannot be resolved or introspected."""


def extract_type(qualified_name: str) -> dict[str, Any]:
    """Return ``{"types": {...}, "root": name, "warnings": [...]}`` for a class.

    ``types`` includes the root type and every nested type it references. The result
    is validated with :func:`validate_library`, so it is guaranteed loadable.
    """
    obj = _resolve(qualified_name)
    types: dict[str, Any] = {}
    warnings: list[str] = []
    root = _emit_type(obj, types, warnings)
    if root is None:
        raise TypeExtractError(
            f"'{qualified_name}' is not a structured type "
            "(expected a TypedDict, dataclass, or Pydantic model)"
        )
    validate_library(types)
    return {"types": types, "root": root, "warnings": warnings}


def _resolve(qualified_name: str) -> Any:
    """Resolve ``module.sub.ClassName`` to the object, trying module prefixes."""
    parts = (qualified_name or "").split(".")
    if len(parts) < 2:
        raise TypeExtractError("Qualified name must look like 'module.ClassName'")
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
                raise TypeExtractError(
                    f"'{qualified_name}': '{attr}' not found in module '{module_name}'"
                ) from exc
        return obj
    raise TypeExtractError(f"Could not import a module from '{qualified_name}'")


def _emit_type(cls: Any, types: dict[str, Any], warnings: list[str]) -> str | None:
    """Register ``cls`` (and nested refs) into ``types``; return its name, or None."""
    fields = _class_fields(cls, warnings)
    if fields is None:
        return None
    name = cls.__name__
    if name not in types:
        # Register before recursing so a self/mutual reference resolves to the name.
        types[name] = {"description": _first_doc_line(cls), "fields": {}}
        types[name]["fields"] = {
            field_name: _emit_field(annotation, required, types, warnings, f"{name}.{field_name}")
            for field_name, (annotation, required) in fields.items()
        }
    return name


def _class_fields(cls: Any, warnings: list[str]) -> dict[str, tuple[Any, bool]] | None:
    """Return ``{field_name: (annotation, required)}`` for a structured class, else None."""
    if not isinstance(cls, type):
        return None
    if typing.is_typeddict(cls):
        hints = _safe_hints(cls)
        required_keys = getattr(cls, "__required_keys__", frozenset())
        return {name: (hint, name in required_keys) for name, hint in hints.items()}
    if dataclasses.is_dataclass(cls):
        hints = _safe_hints(cls)
        result: dict[str, tuple[Any, bool]] = {}
        for field in dataclasses.fields(cls):
            required = field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
            result[field.name] = (hints.get(field.name, field.type), required)
        return result
    model_fields = getattr(cls, "model_fields", None)
    if isinstance(model_fields, dict):  # Pydantic v2 BaseModel
        result = {}
        for name, info in model_fields.items():
            is_required = getattr(info, "is_required", None)
            required = bool(is_required()) if callable(is_required) else True
            result[name] = (getattr(info, "annotation", Any), required)
        return result
    return None


def _emit_field(
    annotation: Any,
    required: bool,
    types: dict[str, Any],
    warnings: list[str],
    path: str,
) -> dict[str, Any]:
    annotation, optional = _strip_optional(annotation)
    if optional:
        required = False
    container = "single"
    origin = get_origin(annotation)
    if origin in (list, set, tuple, frozenset):
        container = "list"
        args = get_args(annotation)
        annotation = args[0] if args else str
    elif origin in (dict,) or (origin is not None and _is_mapping(origin)):
        container = "map"
        args = get_args(annotation)
        annotation = args[1] if len(args) >= 2 else str
    field_type, options = _leaf_or_ref(annotation, types, warnings, path)
    spec: dict[str, Any] = {"type": field_type, "required": required}
    if container != "single":
        spec["container"] = container
    if options is not None:
        spec["options"] = options
    return spec


def _leaf_or_ref(
    annotation: Any,
    types: dict[str, Any],
    warnings: list[str],
    path: str,
) -> tuple[str, list[Any] | None]:
    if get_origin(annotation) is typing.Literal:
        return "enum", list(get_args(annotation))
    if annotation in _PRIMITIVES:
        return _PRIMITIVES[annotation], None
    if isinstance(annotation, type):
        nested = _emit_type(annotation, types, warnings)
        if nested:
            return nested, None
    warnings.append(f"{path}: unsupported type {_label(annotation)} — treated as a string")
    return "string", None


def _strip_optional(annotation: Any) -> tuple[Any, bool]:
    """Unwrap ``Optional[X]`` / ``X | None`` -> ``(X, True)``; pass others through."""
    origin = get_origin(annotation)
    if origin is typing.Union or origin is getattr(_types, "UnionType", object()):
        args = list(get_args(annotation))
        non_none = [arg for arg in args if arg is not _NONE_TYPE]
        had_none = len(non_none) != len(args)
        if len(non_none) == 1:
            return non_none[0], had_none
        return annotation, had_none
    return annotation, False


def _is_mapping(origin: Any) -> bool:
    try:
        import collections.abc as abc

        return isinstance(origin, type) and issubclass(origin, abc.Mapping)
    except TypeError:
        return False


def _safe_hints(cls: Any) -> dict[str, Any]:
    try:
        return typing.get_type_hints(cls)
    except Exception:  # noqa: BLE001 - unresolved forward refs etc.; fall back to raw
        return dict(getattr(cls, "__annotations__", {}))


def _first_doc_line(cls: Any) -> str:
    doc = (inspect.getdoc(cls) or "").strip()
    return doc.split("\n", 1)[0] if doc else ""


def _label(annotation: Any) -> str:
    return getattr(annotation, "__name__", None) or str(annotation)
