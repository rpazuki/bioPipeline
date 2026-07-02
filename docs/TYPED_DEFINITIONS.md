# Typed Definitions — Structured types for published-job fields

Status: **Implemented (Phases 1–5).** Backend core + project type library + Python-class extractor
on the Environment page + admin type-picker + researcher structured editor + multi-instance saved
cases (named saved values with a default). See §10.

Decisions locked with the user:

- **Container shapes:** a published field may expose a defined type as a **single** object, an
  ordered **list**, or a string-keyed **map** (add / edit / delete in all three). The map shape is
  required by the motivating case (`custom_rules`).
- **A project-level type library, not a per-job block.** Named types live in one reusable
  **type library** managed on the **Environment page** (next to package management — the Python
  packages a type is extracted from are installed there). This **replaces** the originally sketched
  in-YAML `definitions:` block: the Job Definition YAML is unchanged, and typed-ness lives entirely
  in the published-field layer.
- **Extraction:** a tool that **introspects a Python class** (TypedDict / dataclass / Pydantic) into
  library types, surfaced as an admin endpoint plus an **Environment-page button** (co-located with
  the library and the package installer).
- **Unknown object fields are rejected** at submit (fail closed).
- **Suggestions are cheap and on-demand.** Inspect may *suggest* a library type when a value's shape
  matches one (it never auto-applies, and runs only during the explicit inspect action — never a hot
  loop).
- **Delivery:** design note first, then phased implementation.

---

## 1. Motivation: the "everything-is-a-string" gap

A Job Definition can pass structured arguments to a process. In
`OD600_growth_rates_ingestion.yaml:48` the `df_replicate_stats` process receives:

```yaml
process_arg_mapping:
  df_replicate_stats:
    custom_rules:
      SLAB:  {direction: alphabetical, sample_size: 3}
      purB:  {direction: alphabetical, sample_size: 3}
      WT:    {direction: alphabetical, sample_size: 2}
      BLANK: {direction: alphabetical, sample_size: 1}
```

`custom_rules` is typed in `labUtils` as `dict[str, CustomReplicateRule]`, where
`CustomReplicateRule` is a `TypedDict(total=False)` with `direction: str`, `pattern: str`,
`sample_size: int` (`media_bot.py:78`).

When this job is **published**, the inspector classifies the value purely by its runtime shape —
`_infer_field_type` returns `"object"` for any dict (`published_jobs.py:956`) — and the researcher
form renders `object` / `json` / `list` as a **raw JSON `<textarea>`**
(`published-jobs/page.tsx:144`). The researcher must hand-type valid JSON with no field names, no
enum choices, and no validation until submit fails. That is the "the only option is string"
limitation.

The fix is to let a definition **declare named types**, let an admin **bind a field to a type** at
publish time, and render a **structured editor** instead of a textarea.

---

## 2. Conceptual model

```
Type Library (project-level, managed on the Environment page)
  └── TypeName
        └── fields → leaf primitives | refs to other TypeNames (+ container)

Job Definition YAML (unchanged)
  └── stages
        └── process_arg_mapping → a value is bound to a library TypeName at publish time

Published field (publish-time binding)
  └── { type: "typed", schema_ref: TypeName, container, type_schema: <resolved tree> }
```

The library is the single source of named types; the Job Definition YAML keeps its existing
shape. A field opts into a type at publish time (`schema_ref` + `container`), and the resolved
structure is denormalized onto the field — so run time never reads the library.

- A **type** is a named bag of fields.
- A **field** has a `type` that is either a **leaf primitive** (reuses the existing
  `FIELD_TYPES`) or the **name of another type** (recursion), wrapped in a **container**
  (`single` / `list` / `map`).
- Types form a tree (a type may reference other types) whose **leaves are primitives**.
- At **publish** time the admin attaches `{schema_ref, container}` to a candidate field; the
  resolved structure is denormalized onto the published field, exactly like `options` and
  `bindings` are today.

The **same field descriptor** is used inside a definition and at the binding site, so nesting is
uniform.

---

## 3. A type in the library

Each library entry is `TypeName -> { description, fields }`, stored in one YAML file
(`<home>/type_library.yaml`) and edited via the admin-only `type-library` CRUD route:

```yaml
CustomReplicateRule:
  description: One strain's replicate-aggregation rule
  fields:
    direction:
      type: enum
      options: [alphabetical, numerical]
      required: false
    pattern:
      type: string
      required: false
    sample_size:
      type: integer
      required: false
```

A field descriptor:

| key         | meaning                                                                 | default   |
|-------------|-------------------------------------------------------------------------|-----------|
| `type`      | a **leaf primitive** or a **defined type name** (required)              | —         |
| `container` | `single` \| `list` \| `map`                                             | `single`  |
| `options`   | choices when `type: enum`                                               | —         |
| `required`  | whether the researcher must supply it                                   | `true`    |
| `default`   | pre-filled value                                                        | —         |
| `help` / `example` | researcher-facing hints                                          | —         |

**Leaf primitives** are the scalar members of the existing `FIELD_TYPES`
(`published_jobs.py:26`): `string, text, integer, float, boolean, enum, path, file, directory,
glob, datetime`. The structural members (`list`, `object`, `json`) remain as the **untyped
fallback** for fields no one has typed yet — nothing about today's behavior changes until an admin
opts a field into a type.

### Nesting and containers

```yaml
definitions:
  Threshold:
    fields:
      metric: { type: string }
      cutoff: { type: float }
  StrainPolicy:
    fields:
      rule:        { type: CustomReplicateRule }              # single nested type
      thresholds:  { type: Threshold, container: list }        # list of a type
      overrides:   { type: CustomReplicateRule, container: map }# map<string, type>
      tags:        { type: string, container: list }           # list of a primitive
```

### Binding at publish time

The motivating field becomes (admin choice in the editor, not authored in YAML):

```
schema_ref: CustomReplicateRule
container:  map
```

— i.e. `custom_rules` is a `map<string, CustomReplicateRule>`.

---

## 4. The published field shape

A new `type` value, **`typed`**, is added to `FIELD_TYPES` and to the TS `PublishedFieldType`
union. A typed field carries three extra attributes; the resolved `type_schema` is **re-derived
from the library on every save** (so it can never pin a stale structure). Editing the library
itself also cascades: `refresh_typed_field_schemas` re-resolves and rewrites the frozen
`type_schema` on every published job that references a type whenever that type is upserted or
deleted (`type-library` route), so already-published jobs follow the edit — a field made optional
in the library stops being rejected as required on jobs published earlier. `schema_ref` and
`container` are **admin-curated** (will be added to `CURATED_FIELD_KEYS`,
`published-jobs-admin/page.tsx:87`, in the admin-picker phase):

```jsonc
{
  "id": "stage_..._process_df_replicate_stats_custom_rules",
  "label": "Custom replicate rules",
  "type": "typed",
  "schema_ref": "CustomReplicateRule",
  "container": "map",
  "type_schema": {
    "name": "CustomReplicateRule",
    "fields": [
      { "name": "direction",   "type": "enum",    "container": "single",
        "options": [{"label":"alphabetical","value":"alphabetical"},
                    {"label":"numerical","value":"numerical"}], "required": false },
      { "name": "pattern",     "type": "string",  "container": "single", "required": false },
      { "name": "sample_size", "type": "integer", "container": "single", "required": false }
    ]
  },
  "bindings": [{ "target": "stage_process_arg", "stage": "...",
                 "process": "df_replicate_stats", "parameter": "custom_rules" }]
}
```

The existing `stage_process_arg` binding is unchanged — it already writes the value into
`process_arg_mapping[process][param]` (`published_jobs.py:853`). The only new work is producing a
**real dict/list** for it instead of a JSON string.

---

## 5. Validation

### Library write time (`validate_library`, in `type_schema.py`; called by the store on every upsert/delete)

- The library is a mapping of `TypeName → { description?, fields }`; names are valid identifiers.
- Each field `type` resolves to a known **leaf primitive** or a **defined type name**.
- `container ∈ {single, list, map}`.
- `enum` leaf fields carry a non-empty `options` list.
- **No reference cycles** (`A → B → A`) — the same DFS cycle check used for stage `needs`
  (`job_definition.py:152`), re-implemented in `type_schema._check_no_cycles`. A cycle would make
  the editor infinitely deep.
- Unknown `type` → error naming the unresolved reference and listing the defined types.

### Submit time (`_coerce_value` for `typed`, in `published_jobs.py`)

- `single`: value is a mapping; each declared field is coerced by its leaf type (reusing the
  existing scalar coercions); `enum` values must be among `options`; missing required leaves with
  no default → error; unknown keys → error (fail closed).
- `list`: value is a list; each element validated as `single`.
- `map`: value is a mapping `string → object`; each entry validated as `single`; keys are
  non-empty strings.
- Nested typed fields recurse. The `$WILL_PROVIDE$` guard (`published_jobs.py:795`) still applies
  to the whole value.

---

## 6. Extracting a type from a Python class

Yes — feasible with the standard `typing` machinery. The target classes (`labUtils.*`) are already
importable in the backend process.

### Endpoint (admin-only, Phase 2)

```
POST /type-library/extract
  { "qualified_name": "labUtils.media_bot.CustomReplicateRule" }
→ { "types": { "CustomReplicateRule": { "description": "...", "fields": { ... } } },
    "root": "CustomReplicateRule",
    "warnings": [] }
```

`importlib.import_module` + `getattr` resolves the class; the response includes the root type **and
every nested type it references**, so the result is self-contained. The Environment-page button
posts the qualified name, previews the types, and (on confirm) upserts each into the library via
`PUT /type-library/{name}`.

### Type mapping

| Python annotation                         | Schema field                                |
|-------------------------------------------|---------------------------------------------|
| `str`                                     | `type: string`                              |
| `int` / `float` / `bool`                  | `integer` / `float` / `boolean`             |
| `Literal["a", "b"]`                       | `type: enum`, `options: [a, b]`             |
| `Enum` subclass (incl. `StrEnum`/`IntEnum`) | `type: enum`, `options: [{label: NAME, value}]` |
| `X | None`, `Optional[X]`                 | underlying `X`, `required: false`           |
| `list[X]` / `List[X]`                     | `X` with `container: list`                  |
| `dict[str, X]` / `Mapping[str, X]`        | `X` with `container: map`                   |
| nested `TypedDict` / dataclass / `BaseModel` | emit a nested named type, `type: <Name>` |
| anything else                             | `string` (fallback **+ warning**)           |

Required vs optional:

- **TypedDict:** `__required_keys__` / `__optional_keys__` (honors `total=`).
- **dataclass:** optional when it has a `default` / `default_factory`.
- **Pydantic:** `model_fields[name].is_required()`.

### Edge cases

- **Self-referential / mutually recursive** Python types → the extractor emits the ref (schema
  allows it) but reports a warning; the parse-time cycle check rejects true cycles, and the editor
  caps render depth regardless.
- **Forward refs / string annotations** → resolved by `get_type_hints` where the module scope
  allows; otherwise fall back to string + warning.
- **Unsupported unions** (e.g. `int | str`) → string leaf + warning.
- **Name collision** with an existing definition → endpoint returns the block and flags the
  conflicting names; the admin reconciles (rename or keep).

---

## 7. End-to-end flow

1. **Define the type** once in the library (Environment page) — by hand or via **Extract from
   Python class**. The Job Definition YAML itself is unchanged.
2. **Inspect** emits the `custom_rules` candidate (`_stage_candidates`, `published_jobs.py:663`) and
   may attach a non-binding `schema_suggestion`. The admin picks `schema_ref` + `container`.
3. **Publish** persists `type: typed` + curated `schema_ref` / `container`; `type_schema`
   re-resolves from the library on each save (`resolve_typed_fields`), like `options` today.
4. **Fill**: the researcher gets a structured editor producing a native object / list / dict.
5. **Coerce / validate** against `type_schema`; the native structure flows through the unchanged
   `stage_process_arg` binding into the rendered definition.
6. **Result**: the rendered Job Definition carries a proper `custom_rules` dict — exactly what
   `df_replicate_stats` expects.

---

## 8. Researcher editor UX (`TypedValueEditor.tsx`, new)

Given `{type_schema, container, value, onChange}`:

- **single** — one sub-form: each `type_schema.fields[i]` rendered with the existing leaf inputs
  (`FieldInput`, `published-jobs/page.tsx:91`), recursing into nested typed fields.
- **list** — a column of single-editors with **Add** / **Delete** (and reorder); value is an array.
- **map** — rows of **[key input] + single-editor** with **Add** / **Delete**; keys must be unique
  and non-empty; value is an object.

The published-jobs page swaps the JSON textarea for `<TypedValueEditor>` when
`field.type === "typed"`; the readonly path renders a compact summary.

---

## 9. Worked example: `custom_rules`

**Library type** (hand-written, or extracted from `labUtils.media_bot.CustomReplicateRule`):

```yaml
CustomReplicateRule:
  fields:
    direction:   { type: enum, options: [alphabetical, numerical], required: false }
    pattern:     { type: string, required: false }
    sample_size: { type: integer, required: false }
```

**Publish:** bind the `df_replicate_stats.custom_rules` field → `schema_ref: CustomReplicateRule`,
`container: map`.

**Before → After (researcher view):**

| Before                                   | After                                                              |
|------------------------------------------|--------------------------------------------------------------------|
| One JSON `<textarea>`; type the whole map | A map editor: rows `SLAB`, `purB`, `WT`, … each with a `direction` dropdown and a `sample_size` number; Add / Delete rows |

---

## 10. Phased rollout

- **Phase 1 — backend core. ✅ Implemented.**
  - `type_schema.py` — `validate_library`, `resolve_type`, `coerce_typed_value`, `suggest_type`,
    cycle check.
  - `type_library_store.py` — single-YAML store (`<home>/type_library.yaml`), validate-on-write;
    wired into `PipelineRuntime` / `create_runtime`.
  - `type-library` CRUD route (admin-only) + `TypeDef*` schemas, registered in `main.py`.
  - `published_jobs.py` — `typed` in `FIELD_TYPES`; `_coerce_value` typed branch;
    `resolve_typed_fields` (denormalize `type_schema` at save); `inspect_definition` suggestion
    hook; field validation. `PublishedField` / `PublicPublishedField` gain
    `schema_ref` / `container` / `type_schema`; TS contract updated.
  - Tests: `tests/unit/test_type_schema.py`, `test_type_library_store.py`,
    `test_published_typed_fields.py`, `backend/tests/test_type_library_routes.py`.
- **Phase 2 — library management on the Environment page. ✅ Implemented.**
  - `type_extract.py` — `extract_type(qualified_name)` introspects a TypedDict / dataclass /
    Pydantic model into library entries (the mapping table above), recursing into nested types.
  - `POST /type-library/extract` (admin-only) + `TypeExtract*` schemas; tests in
    `tests/unit/test_type_extract.py` and `backend/tests/test_type_library_routes.py`.
  - `TypeLibraryPanel.tsx` on the Environment page: list / create / edit / delete types, and an
    **Extract from a Python class** box (paste a qualified name → preview the types + warnings →
    upsert). API client + TS types added.
- **Phase 3 — admin picker. ✅ Implemented.** In the Definable Fields panel
  (`published-jobs-admin/page.tsx`): a **Structured type** dropdown (library types) plus a **Shape**
  dropdown (single / list / map) for plain-value fields, an **apply** button for the inspector's
  `schema_suggestion`, and switching a field to file I/O clears any typed binding (mutually
  exclusive). `schema_ref` / `container` added to `CURATED_FIELD_KEYS`; `mergeFields` keeps a field
  `typed` across re-inspect when `schema_ref` is set; the library is loaded via `listTypeLibrary`.
- **Phase 4 — researcher editor. ✅ Implemented.** `TypedValueEditor.tsx` (single = sub-form,
  list = add/remove ordered rows, map = add/remove keyed rows, recursive into nested typed fields)
  replaces the JSON textarea on the published-jobs page when `field.type === "typed"`; falls back to
  JSON if a field's resolved schema is missing. Typed fields render in a `<div>` (not a `<label>`)
  so clicks aren't mis-routed; the researcher detail exposes `type_schema` + `container` (bindings
  stripped). Component tests in `TypedValueEditor.test.tsx` cover single/list/map.
- **Phase 5 — multi-instance saved cases. ✅ Implemented.** An admin can mark a library type
  `multiple` (a boolean on the type, next to `description`/`fields`; a checkbox in
  `TypeLibraryPanel.tsx`). The flag rides on the resolved `type_schema` (`resolve_type`) so every
  bound field and saved record sees it. A researcher may then keep **several named cases** of that
  type with exactly one flagged **default**: the saved-value store keys records by
  `(user_id, type_key, container, name)` — `name=""` for a single-instance type — and exposes
  `get_default` / `list_cases` / `set_default`, promoting a sibling when the default is deleted
  (`typed_value_store.py`; a one-time table rebuild relaxes the old 3-column unique constraint on
  existing DBs). The `/saved-typed-values` route stamps `multiple` from the live library (researchers
  can't read the admin `/type-library` route), forces a single-instance `name` empty, and forwards
  `name` / `make_default`. On the run form the default case pre-fills and a shared
  `SavedCasesControl.tsx` switches / adds / renames / deletes / re-defaults cases inline; the **Saved
  Values** page is now master/detail — a list of saved types, each opening its editor (a single value
  as-is, or its named cases when `multiple`). Tests: `tests/unit/test_typed_value_store.py`
  (cases + default promotion + legacy-DB migration), extended `test_saved_typed_values_routes.py` /
  `test_type_library_routes.py` / `test_type_schema.py`, and `SavedCasesControl.test.tsx` +
  the published-jobs page test.

---

## 11. Resolved questions

1. **Untyped-dict autodetection** — *suggest, cheaply.* Inspect attaches a non-binding
   `schema_suggestion` when a value's shape matches a library type. It runs only during the explicit
   inspect action (never a hot loop) and never auto-applies.
2. **Unknown keys at submit** — *reject* (fail closed); `_coerce_object` raises on unknown fields.
3. **Type location** — *a reusable project-level library on the Environment page*, replacing the
   originally sketched in-YAML `definitions:` block. Co-located with package management so the
   Python packages a type is extracted from are installed in the same place.
