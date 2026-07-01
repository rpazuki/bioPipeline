"""Named-type schema: the reusable type library behind structured published fields.

A *type library* is a project-level registry of named types. A type is one of:

- **Compound** — a bag of **fields**; a field's ``type`` is either a **leaf primitive**
  (a scalar member of the published-field type set) or the **name of another type** in
  the library (recursion), wrapped in a ``container`` of ``single`` / ``list`` / ``map``.
- **Simple (scalar)** — a single primitive value, declared with a top-level ``type``
  (a leaf primitive, e.g. ``{type: string}`` or ``{type: enum, options: [...]}``) and
  no ``fields``. Bound to a published field it edits as one scalar (``single``), a list
  of scalars (``list``), or a string-keyed map of scalars (``map``).

Types form a tree whose leaves are primitives.

The library lets a published-job field be edited as a structured value (e.g. a
``map`` of ``CustomReplicateRule``) instead of a raw JSON textarea. Three operations
matter:

- :func:`validate_library` — structural validation (known refs, valid containers,
  enums carry options, no reference cycles).
- :func:`resolve_type` — flatten one type into a self-contained ``type_schema`` tree
  that is denormalized onto a published field, so run time never needs the library.
- :func:`coerce_typed_value` — validate + coerce a researcher's value against a
  resolved ``type_schema`` (fail-closed on unknown fields and invalid enums).

See ``docs/TYPED_DEFINITIONS.md`` for the full design.
"""

from __future__ import annotations

from typing import Any

# Leaf primitives a type's field may use. These mirror the scalar members of
# published_jobs.FIELD_TYPES; the structural members (list/object/json) are
# expressed here as containers, not leaf types.
LEAF_TYPES = {
    "string",
    "text",
    "integer",
    "float",
    "boolean",
    "enum",
    "path",
    "file",
    "directory",
    "glob",
    "datetime",
}

CONTAINERS = {"single", "list", "map"}


class TypeSchemaError(ValueError):
    """Raised when a type library, a type reference, or a typed value is invalid."""


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate_library(library: dict[str, Any]) -> None:
    """Structurally validate a whole type library; raise :class:`TypeSchemaError`."""
    if not isinstance(library, dict):
        raise TypeSchemaError("Type library must be a mapping of name -> type")
    names = set(library)
    for name, type_def in library.items():
        if not isinstance(name, str) or not name.strip():
            raise TypeSchemaError("Each type needs a non-empty name")
        if _is_scalar_type(type_def):
            _validate_scalar(name, type_def)
            continue
        fields = _fields_of(name, type_def)
        for field_name, spec in fields.items():
            _validate_field(name, field_name, spec, names)
    _check_no_cycles(library)


def _is_scalar_type(type_def: Any) -> bool:
    """True for a *simple* type: a single primitive (``type``), with no ``fields``."""
    return isinstance(type_def, dict) and not type_def.get("fields") and bool(type_def.get("type"))


def _validate_scalar(name: str, type_def: dict[str, Any]) -> None:
    """A simple type must be a leaf primitive (enums carry options)."""
    field_type = type_def.get("type")
    if field_type not in LEAF_TYPES:
        raise TypeSchemaError(
            f"Simple type '{name}' must be a primitive "
            f"({', '.join(sorted(LEAF_TYPES))}); got '{field_type}'."
        )
    if field_type == "enum" and not type_def.get("options"):
        raise TypeSchemaError(f"Simple type '{name}' is an enum but lists no 'options'")


def _fields_of(name: str, type_def: Any) -> dict[str, Any]:
    if not isinstance(type_def, dict):
        raise TypeSchemaError(f"Type '{name}' must be a mapping")
    fields = type_def.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise TypeSchemaError(f"Type '{name}' must have a non-empty 'fields' mapping")
    return fields


def _validate_field(type_name: str, field_name: str, spec: Any, names: set[str]) -> None:
    where = f"{type_name}.{field_name}"
    if not isinstance(spec, dict):
        raise TypeSchemaError(f"Field '{where}' must be a mapping")
    field_type = spec.get("type")
    if not isinstance(field_type, str) or not field_type:
        raise TypeSchemaError(f"Field '{where}' needs a 'type'")
    container = spec.get("container", "single")
    if container not in CONTAINERS:
        raise TypeSchemaError(
            f"Field '{where}' has invalid container '{container}' (use single, list, or map)"
        )
    if field_type not in LEAF_TYPES and field_type not in names:
        raise TypeSchemaError(
            f"Field '{where}' references unknown type '{field_type}'. "
            f"Use a primitive ({', '.join(sorted(LEAF_TYPES))}) or a defined type "
            f"({', '.join(sorted(names)) or 'none defined'})."
        )
    if field_type == "enum" and not spec.get("options"):
        raise TypeSchemaError(f"Field '{where}' is an enum but lists no 'options'")


def _check_no_cycles(library: dict[str, Any]) -> None:
    """Reject reference cycles (A -> B -> A) — they make the editor infinitely deep."""
    edges: dict[str, list[str]] = {}
    for name, type_def in library.items():
        refs = [
            spec.get("type")
            for spec in (type_def.get("fields") or {}).values()
            if isinstance(spec, dict) and spec.get("type") in library
        ]
        edges[name] = refs
    state: dict[str, int] = {}  # 0 = visiting, 1 = done

    def visit(node: str, trail: list[str]) -> None:
        seen = state.get(node)
        if seen == 1:
            return
        if seen == 0:
            raise TypeSchemaError("Type reference cycle: " + " -> ".join(trail + [node]))
        state[node] = 0
        for nxt in edges.get(node, []):
            visit(nxt, trail + [node])
        state[node] = 1

    for node in edges:
        visit(node, [])


# --------------------------------------------------------------------------- #
# Resolution — flatten a named type into a self-contained schema tree
# --------------------------------------------------------------------------- #
def resolve_type(library: dict[str, Any], type_name: str, *, _seen: tuple[str, ...] = ()) -> dict[str, Any]:
    """Return a self-contained ``{name, fields:[...]}`` tree for ``type_name``.

    Each field node carries ``name``, ``type`` (a leaf primitive or ``"typed"``),
    ``container``, ``required``, ``options`` (enums), and — when it references another
    type — ``schema_ref`` plus a nested ``type_schema``. The result needs no further
    library lookups, so it can be denormalized onto a published field.
    """
    if type_name not in library:
        raise TypeSchemaError(f"Unknown type '{type_name}'")
    if type_name in _seen:
        raise TypeSchemaError("Type reference cycle through '%s'" % type_name)
    type_def = library[type_name]
    if _is_scalar_type(type_def):
        # A simple type resolves to a single leaf descriptor under ``scalar`` (rather
        # than a ``fields`` list), tagged ``kind: scalar`` so consumers render/coerce a
        # bare value instead of an object.
        field_type = type_def["type"]
        scalar: dict[str, Any] = {
            "type": field_type,
            "options": _normalize_options(type_def.get("options")) if field_type == "enum" else [],
            "help": str(type_def.get("help", "")),
            "example": str(type_def.get("example", "")),
        }
        if "default" in type_def:
            scalar["default"] = type_def["default"]
        return {"name": type_name, "kind": "scalar", "scalar": scalar}
    fields: list[dict[str, Any]] = []
    for field_name, spec in (_fields_of(type_name, type_def)).items():
        field_type = spec["type"]
        is_leaf = field_type in LEAF_TYPES
        node: dict[str, Any] = {
            "name": field_name,
            "type": field_type if is_leaf else "typed",
            "container": spec.get("container", "single"),
            "required": bool(spec.get("required", True)),
            "options": _normalize_options(spec.get("options")) if field_type == "enum" else [],
            "help": str(spec.get("help", "")),
            "example": str(spec.get("example", "")),
        }
        if "default" in spec:
            node["default"] = spec["default"]
        if not is_leaf:
            node["schema_ref"] = field_type
            node["type_schema"] = resolve_type(library, field_type, _seen=_seen + (type_name,))
        fields.append(node)
    return {"name": type_name, "fields": fields}


def _normalize_options(options: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for option in options or []:
        if isinstance(option, dict) and "value" in option:
            normalized.append({"label": str(option.get("label", option["value"])), "value": option["value"]})
        else:
            normalized.append({"label": str(option), "value": option})
    return normalized


# --------------------------------------------------------------------------- #
# Coercion — validate a researcher value against a resolved schema
# --------------------------------------------------------------------------- #
def coerce_typed_value(field: dict[str, Any], value: Any) -> Any:
    """Validate + coerce ``value`` for a typed field (``container`` + ``type_schema``).

    Returns a native object / list / dict. Fails closed: unknown object fields and
    invalid enum values raise :class:`TypeSchemaError`.
    """
    container = field.get("container", "single")
    schema = field.get("type_schema")
    if not isinstance(schema, dict):
        raise TypeSchemaError("Typed field is missing its resolved schema")
    label = str(field.get("label") or field.get("name") or schema.get("name") or "value")
    # A simple (scalar) type coerces a bare leaf value (or a list/map of them).
    if schema.get("kind") == "scalar":
        return _coerce_scalar_container(schema, container, value, label)
    if container == "single":
        return _coerce_object(schema, value, label)
    if container == "list":
        if not isinstance(value, list):
            raise TypeSchemaError(f"'{label}' must be a list of {schema.get('name')}")
        return [_coerce_object(schema, item, f"{label}[{index}]") for index, item in enumerate(value)]
    if container == "map":
        if not isinstance(value, dict):
            raise TypeSchemaError(f"'{label}' must be a map of {schema.get('name')}")
        coerced: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise TypeSchemaError(f"'{label}' has an empty entry key")
            coerced[key] = _coerce_object(schema, item, f"{label}.{key}")
        return coerced
    raise TypeSchemaError(f"Unknown container '{container}'")


def _coerce_scalar_container(schema: dict[str, Any], container: str, value: Any, label: str) -> Any:
    """Coerce a value against a resolved *simple* type for single/list/map containers."""
    leaf = schema.get("scalar") or {}
    name = schema.get("name")
    if container == "single":
        return _coerce_leaf(leaf, value, label)
    if container == "list":
        if not isinstance(value, list):
            raise TypeSchemaError(f"'{label}' must be a list of {name}")
        return [_coerce_leaf(leaf, item, f"{label}[{index}]") for index, item in enumerate(value)]
    if container == "map":
        if not isinstance(value, dict):
            raise TypeSchemaError(f"'{label}' must be a map of {name}")
        coerced: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise TypeSchemaError(f"'{label}' has an empty entry key")
            coerced[key] = _coerce_leaf(leaf, item, f"{label}.{key}")
        return coerced
    raise TypeSchemaError(f"Unknown container '{container}'")


def _coerce_object(schema: dict[str, Any], value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeSchemaError(f"'{label}' must be an object ({schema.get('name')})")
    by_name = {field["name"]: field for field in schema.get("fields", [])}
    unknown = set(value) - set(by_name)
    if unknown:
        raise TypeSchemaError(f"'{label}' has unknown field(s): {', '.join(sorted(unknown))}")
    result: dict[str, Any] = {}
    for field_name, node in by_name.items():
        has_value = field_name in value and value[field_name] not in (None, "")
        if has_value:
            result[field_name] = _coerce_node(node, value[field_name], f"{label}.{field_name}")
        elif "default" in node:
            result[field_name] = node["default"]
        elif node.get("required", True):
            raise TypeSchemaError(f"'{label}.{field_name}' is required")
        # otherwise: optional and absent — omit it
    return result


def _coerce_node(node: dict[str, Any], value: Any, label: str) -> Any:
    if node.get("type") == "typed":
        return coerce_typed_value(node, value)
    # A leaf field can itself carry a container (e.g. ``levels: list[float]``): coerce
    # each element as a scalar rather than the whole list/map as one value.
    container = node.get("container", "single")
    if container == "list":
        if not isinstance(value, list):
            raise TypeSchemaError(f"'{label}' must be a list")
        return [_coerce_leaf(node, item, f"{label}[{index}]") for index, item in enumerate(value)]
    if container == "map":
        if not isinstance(value, dict):
            raise TypeSchemaError(f"'{label}' must be a map")
        coerced: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise TypeSchemaError(f"'{label}' has an empty entry key")
            coerced[key] = _coerce_leaf(node, item, f"{label}.{key}")
        return coerced
    return _coerce_leaf(node, value, label)


def _coerce_leaf(node: dict[str, Any], value: Any, label: str) -> Any:
    field_type = node.get("type", "string")
    if field_type == "integer":
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise TypeSchemaError(f"'{label}' must be an integer") from exc
    if field_type == "float":
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise TypeSchemaError(f"'{label}' must be a number") from exc
    if field_type == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
        raise TypeSchemaError(f"'{label}' must be a boolean")
    if field_type == "enum":
        for option in node.get("options", []):
            if value == option["value"] or str(value) == str(option["value"]):
                return option["value"]
        allowed = ", ".join(str(option["value"]) for option in node.get("options", []))
        raise TypeSchemaError(f"'{label}' must be one of: {allowed}")
    return value


# --------------------------------------------------------------------------- #
# Suggestion — a cheap structural guess used by the publishing inspector
# --------------------------------------------------------------------------- #
def suggest_type(library: dict[str, Any], value: Any) -> tuple[str, str] | None:
    """Guess ``(type_name, container)`` for a dict / list-of-dict ``value``.

    A best-effort match by field names, run on demand during inspect (never in a
    hot loop). Returns ``None`` when nothing fits.
    """
    if isinstance(value, dict) and value:
        entries = list(value.values())
        if entries and all(isinstance(item, dict) for item in entries):
            name = _match_object(library, entries[0])
            if name and all(_match_object(library, item) == name for item in entries):
                return name, "map"
        name = _match_object(library, value)
        if name:
            return name, "single"
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        name = _match_object(library, value[0])
        if name and all(_match_object(library, item) == name for item in value):
            return name, "list"
    return None


def _match_object(library: dict[str, Any], obj: dict[str, Any]) -> str | None:
    """The tightest library type whose fields are a superset of ``obj``'s keys."""
    keys = set(obj)
    if not keys:
        return None
    best: str | None = None
    best_size = 0
    for name, type_def in library.items():
        fields = set((type_def.get("fields") or {}))
        if keys <= fields and (best is None or len(fields) < best_size):
            best, best_size = name, len(fields)
    return best
