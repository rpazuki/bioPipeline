"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { deleteType, extractType, listTypeLibrary, upsertType } from "@/lib/api";
import type { TypeDef, TypeExtractResponse, TypeFieldSpec } from "@/types";

// Leaf primitives a field may use — mirrors type_schema.LEAF_TYPES. A field's type
// may also be the name of another library type (added to the dropdown at runtime).
const LEAF_TYPES = [
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
];

const CONTAINERS = ["single", "list", "map"] as const;

interface FieldRow {
  key: string;
  type: string;
  container: (typeof CONTAINERS)[number];
  required: boolean;
  options: string; // comma-separated, for enum
  default: string; // optional default; "" means none
}

function rowsFromType(type: TypeDef): FieldRow[] {
  return Object.entries(type.fields ?? {}).map(([key, spec]) => ({
    key,
    type: spec.type ?? "string",
    container: spec.container ?? "single",
    required: spec.required ?? true,
    options: optionsToText(spec.options),
    default: spec.default === undefined || spec.default === null ? "" : String(spec.default),
  }));
}

// A default is optional. When present, parse it into the field's primitive type so
// it is stored as the right kind (e.g. 5 not "5") — the backend assigns it verbatim
// when a researcher leaves the field empty, without re-coercing.
function parseDefault(raw: string, type: string): unknown {
  const text = raw.trim();
  if (!text) return undefined;
  if (type === "integer") {
    const value = Number.parseInt(text, 10);
    return Number.isNaN(value) ? text : value;
  }
  if (type === "float") {
    const value = Number.parseFloat(text);
    return Number.isNaN(value) ? text : value;
  }
  if (type === "boolean") {
    if (/^(true|1|yes|on)$/i.test(text)) return true;
    if (/^(false|0|no|off)$/i.test(text)) return false;
    return text;
  }
  return text;
}

// A simple (scalar) type stores a single primitive `type` and no `fields`.
function isSimpleType(type: TypeDef): boolean {
  return (!type.fields || Object.keys(type.fields).length === 0) && !!type.type;
}

// Enum options round-trip through the comma-separated editor field. An option may be a
// bare scalar or a {label, value} pair (extracted enums use the latter). Render it as
// `value` when the label matches, else `LABEL=value` — a naive String(option) turned
// the pair into the literal "[object Object]", corrupting every extracted enum on edit.
function optionText(option: unknown): string {
  if (option && typeof option === "object" && "value" in option) {
    const value = String((option as { value: unknown }).value ?? "");
    const rawLabel = (option as { label?: unknown }).label;
    const label = rawLabel == null ? value : String(rawLabel);
    return label === value ? value : `${label}=${value}`;
  }
  return String(option);
}

function optionsToText(options: unknown[] | undefined): string {
  return (options ?? []).map(optionText).join(", ");
}

function parseOptions(text: string): unknown[] {
  return text
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean)
    .map((token) => {
      const eq = token.indexOf("=");
      return eq > 0 ? { label: token.slice(0, eq).trim(), value: token.slice(eq + 1).trim() } : token;
    });
}

function fieldsFromRows(rows: FieldRow[]): Record<string, TypeFieldSpec> {
  const fields: Record<string, TypeFieldSpec> = {};
  for (const row of rows) {
    const name = row.key.trim();
    if (!name) continue;
    const spec: TypeFieldSpec = { type: row.type, required: row.required };
    if (row.container !== "single") spec.container = row.container;
    if (row.type === "enum") {
      spec.options = parseOptions(row.options);
    }
    const parsed = parseDefault(row.default, row.type);
    if (parsed !== undefined) spec.default = parsed;
    fields[name] = spec;
  }
  return fields;
}

export default function TypeLibraryPanel() {
  const [types, setTypes] = useState<TypeDef[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  // Editor state
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [rows, setRows] = useState<FieldRow[]>([]);
  const [editing, setEditing] = useState(false);
  // Compound = a bag of fields; simple = one primitive value.
  const [editKind, setEditKind] = useState<"compound" | "simple">("compound");
  // Whether a researcher may save several named cases of this type (with one default).
  const [editMultiple, setEditMultiple] = useState(false);
  const [simpleType, setSimpleType] = useState("string");
  const [simpleOptions, setSimpleOptions] = useState(""); // comma-separated, for enum
  const [simpleDefault, setSimpleDefault] = useState("");

  // Extractor state
  const [qualified, setQualified] = useState("");
  const [preview, setPreview] = useState<TypeExtractResponse | null>(null);

  const typeNames = useMemo(() => types.map((type) => type.name), [types]);
  // Reference choices: leaf primitives + other library types (never self, to avoid an
  // obvious cycle — the backend rejects cycles regardless).
  const typeChoices = useMemo(
    () => [...LEAF_TYPES, ...typeNames.filter((name) => name !== editName)],
    [typeNames, editName],
  );

  const refresh = useCallback(async () => {
    const data = await listTypeLibrary();
    setTypes(data.types);
    setLoaded(true);
  }, []);

  const run = useCallback(async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  // Load the library as soon as the page shows, so the types are visible without
  // an extra click. The Reload button stays for an explicit refresh afterwards.
  useEffect(() => {
    run(refresh);
  }, [run, refresh]);

  function startNew() {
    setEditing(true);
    setEditKind("compound");
    setEditMultiple(false);
    setEditName("");
    setEditDescription("");
    setRows([{ key: "", type: "string", container: "single", required: true, options: "", default: "" }]);
    setSimpleType("string");
    setSimpleOptions("");
    setSimpleDefault("");
    setStatus(null);
  }

  function startEdit(type: TypeDef) {
    setEditing(true);
    setEditName(type.name);
    setEditDescription(type.description ?? "");
    setEditMultiple(!!type.multiple);
    if (isSimpleType(type)) {
      setEditKind("simple");
      setSimpleType(type.type ?? "string");
      setSimpleOptions(optionsToText(type.options));
      setSimpleDefault(type.default === undefined || type.default === null ? "" : String(type.default));
      setRows([]);
    } else {
      setEditKind("compound");
      setRows(rowsFromType(type));
      setSimpleType("string");
      setSimpleOptions("");
      setSimpleDefault("");
    }
    setStatus(null);
  }

  function patchRow(index: number, patch: Partial<FieldRow>) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  const onSave = () =>
    run(async () => {
      const name = editName.trim();
      if (editKind === "simple") {
        const body: { description: string; type: string; options?: unknown[]; default?: unknown; multiple: boolean } = {
          description: editDescription,
          type: simpleType,
          multiple: editMultiple,
        };
        if (simpleType === "enum") {
          body.options = parseOptions(simpleOptions);
        }
        const parsedDefault = parseDefault(simpleDefault, simpleType);
        if (parsedDefault !== undefined) body.default = parsedDefault;
        await upsertType(name, body);
      } else {
        await upsertType(name, { description: editDescription, fields: fieldsFromRows(rows), multiple: editMultiple });
      }
      setStatus(`Saved ${name}`);
      setEditing(false);
      await refresh();
    });

  const onDelete = (name: string) =>
    run(async () => {
      await deleteType(name);
      setStatus(`Deleted ${name}`);
      if (editName === name) setEditing(false);
      await refresh();
    });

  const onExtract = () =>
    run(async () => {
      setPreview(await extractType(qualified.trim()));
    });

  const onImport = () =>
    run(async () => {
      if (!preview) return;
      for (const [name, def] of Object.entries(preview.types)) {
        await upsertType(name, { description: def.description ?? "", fields: def.fields, source: def.source });
      }
      setStatus(`Imported ${Object.keys(preview.types).length} type(s) from ${preview.root}`);
      setPreview(null);
      setQualified("");
      await refresh();
    });

  const canSave =
    editName.trim().length > 0 &&
    (editKind === "simple"
      ? simpleType.length > 0 &&
        (simpleType !== "enum" || simpleOptions.split(",").some((option) => option.trim().length > 0))
      : rows.some((row) => row.key.trim().length > 0));

  return (
    <section className="grid gap-3 rounded-md border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-900">Type library</h2>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => run(refresh)}
            disabled={busy}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 disabled:opacity-50"
          >
            {loaded ? "Reload" : "Load types"}
          </button>
          <button
            type="button"
            onClick={startNew}
            disabled={busy}
            className="rounded-md bg-cyan-700 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
          >
            New type
          </button>
        </div>
      </div>
      <p className="text-xs text-slate-500">
        Named types that admins can bind published-job fields to (e.g. a map of <code>CustomReplicateRule</code>).
        Extract one from an installed Python class, or define it by hand.
      </p>
      {error ? <p className="text-xs text-rose-700">{error}</p> : null}
      {status ? <p className="text-xs text-emerald-700">{status}</p> : null}

      {/* Extract from a Python class */}
      <div className="grid gap-2 rounded-md bg-slate-50 p-3">
        <span className="text-xs font-semibold text-slate-700">Extract from a Python class</span>
        <div className="flex flex-wrap gap-2">
          <input
            value={qualified}
            onChange={(event) => setQualified(event.target.value)}
            placeholder="labUtils.media_bot.CustomReplicateRule"
            className="flex-1 rounded-md border border-slate-300 px-3 py-2 font-mono text-xs"
          />
          <button
            type="button"
            onClick={onExtract}
            disabled={busy || !qualified.trim()}
            className="rounded-md border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-50"
          >
            Extract
          </button>
        </div>
        {preview ? (
          <div className="grid gap-2 rounded-md border border-slate-200 bg-white p-2 text-xs">
            <span className="font-semibold text-slate-800">
              {Object.keys(preview.types).length} type(s) from {preview.root}
            </span>
            {Object.entries(preview.types).map(([name, def]) => (
              <span key={name} className="font-mono text-slate-600">
                {name}: {Object.keys(def.fields ?? {}).join(", ")}
              </span>
            ))}
            {preview.warnings.map((warning, index) => (
              <span key={index} className="text-amber-700">⚠ {warning}</span>
            ))}
            <div className="flex gap-2">
              <button type="button" onClick={onImport} disabled={busy} className="rounded-md bg-emerald-700 px-3 py-1.5 font-semibold text-white disabled:opacity-50">
                Add to library
              </button>
              <button type="button" onClick={() => setPreview(null)} className="rounded-md border border-slate-300 px-3 py-1.5 font-semibold text-slate-600">
                Discard
              </button>
            </div>
          </div>
        ) : null}
      </div>

      {/* Existing types — past 6 the list scrolls so the panel stays compact. */}
      {loaded ? (
        <ul className={`grid gap-1 ${types.length > 6 ? "max-h-72 overflow-y-auto pr-1" : ""}`}>
          {types.length === 0 ? <li className="text-xs text-slate-500">No types defined yet.</li> : null}
          {types.map((type) => (
            <li key={type.name} className="flex items-center justify-between gap-2 rounded-md border border-slate-200 px-3 py-1.5 text-xs">
              <span>
                {/* Show the full import path (e.g. labUtils.synthetic.Foo) when known, so
                    same-named types from different modules are distinguishable; the bare
                    name remains the library key Edit/Delete act on. */}
                <span className="font-mono font-semibold text-slate-900" title={type.source || type.name}>{type.source || type.name}</span>
                <span className="text-slate-400"> · {isSimpleType(type) ? `simple (${type.type})` : `${Object.keys(type.fields ?? {}).length} fields`}</span>
                {type.multiple ? (
                  <span className="ml-1 rounded-full bg-violet-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-700">multiple</span>
                ) : null}
                {type.description ? <span className="text-slate-500"> — {type.description}</span> : null}
              </span>
              <span className="flex gap-2">
                <button type="button" onClick={() => startEdit(type)} className="rounded-md border border-slate-300 px-2 py-0.5 font-semibold text-slate-600">
                  Edit
                </button>
                <button type="button" onClick={() => onDelete(type.name)} disabled={busy} className="rounded-md border border-rose-200 px-2 py-0.5 font-semibold text-rose-700 disabled:opacity-50">
                  Delete
                </button>
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      {/* Editor */}
      {editing ? (
        <div className="grid gap-2 rounded-md border border-cyan-200 bg-cyan-50/40 p-3">
          <div className="flex flex-wrap gap-2">
            <label className="grid gap-1 text-xs font-semibold text-slate-600">
              Type name
              <input
                value={editName}
                onChange={(event) => setEditName(event.target.value)}
                placeholder="CustomReplicateRule"
                className="h-8 rounded-md border border-slate-300 px-2 font-mono text-xs"
              />
            </label>
            <label className="grid flex-1 gap-1 text-xs font-semibold text-slate-600">
              Description
              <input
                value={editDescription}
                onChange={(event) => setEditDescription(event.target.value)}
                className="h-8 rounded-md border border-slate-300 px-2 text-xs font-normal"
              />
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs font-semibold text-slate-600">
            <span>Kind</span>
            <label className="flex items-center gap-1 font-normal">
              <input type="radio" name="type-kind" checked={editKind === "compound"} onChange={() => setEditKind("compound")} />
              Compound (multiple fields)
            </label>
            <label className="flex items-center gap-1 font-normal">
              <input type="radio" name="type-kind" checked={editKind === "simple"} onChange={() => setEditKind("simple")} />
              Simple (one value)
            </label>
          </div>

          <label className="flex items-center gap-2 text-xs font-normal text-slate-600">
            <input type="checkbox" checked={editMultiple} onChange={(event) => setEditMultiple(event.target.checked)} />
            <span>
              <span className="font-semibold text-slate-700">Allow multiple saved cases</span> — researchers can
              save several named values of this type and pick one as their default.
            </span>
          </label>

          {editKind === "simple" ? (
            <div className="grid gap-1">
              <span className="text-xs font-semibold text-slate-600">Value</span>
              <div className="flex flex-wrap items-center gap-1.5">
                <select value={simpleType} onChange={(event) => setSimpleType(event.target.value)} className="h-8 rounded-md border border-slate-300 px-1 text-xs">
                  {LEAF_TYPES.map((choice) => (
                    <option key={choice} value={choice}>{choice}</option>
                  ))}
                </select>
                <input
                  value={simpleDefault}
                  onChange={(event) => setSimpleDefault(event.target.value)}
                  placeholder="default (optional)"
                  title="Optional default value used when a researcher leaves this field empty"
                  className="h-8 w-36 rounded-md border border-slate-300 px-2 text-xs"
                />
                {simpleType === "enum" ? (
                  <input
                    value={simpleOptions}
                    onChange={(event) => setSimpleOptions(event.target.value)}
                    placeholder="aerobic, HIGH=high"
                    className="h-8 flex-1 rounded-md border border-slate-300 px-2 text-xs"
                  />
                ) : null}
              </div>
              <span className="text-[11px] text-slate-400">
                A single {simpleType} value. Bound to a job field it can be used as one value, a list, or a map.
              </span>
            </div>
          ) : (
          <div className="grid gap-1">
            <span className="text-xs font-semibold text-slate-600">Fields</span>
            {rows.map((row, index) => (
              <div key={index} className="flex flex-wrap items-center gap-1.5">
                <input
                  value={row.key}
                  onChange={(event) => patchRow(index, { key: event.target.value })}
                  placeholder="field name"
                  className="h-8 w-36 rounded-md border border-slate-300 px-2 font-mono text-xs"
                />
                <select value={row.type} onChange={(event) => patchRow(index, { type: event.target.value })} className="h-8 rounded-md border border-slate-300 px-1 text-xs">
                  {typeChoices.map((choice) => (
                    <option key={choice} value={choice}>{choice}</option>
                  ))}
                </select>
                <select value={row.container} onChange={(event) => patchRow(index, { container: event.target.value as FieldRow["container"] })} className="h-8 rounded-md border border-slate-300 px-1 text-xs">
                  {CONTAINERS.map((container) => (
                    <option key={container} value={container}>{container}</option>
                  ))}
                </select>
                <label className="flex items-center gap-1 text-xs text-slate-600">
                  <input type="checkbox" checked={row.required} onChange={(event) => patchRow(index, { required: event.target.checked })} />
                  req
                </label>
                {LEAF_TYPES.includes(row.type) ? (
                  <input
                    value={row.default}
                    onChange={(event) => patchRow(index, { default: event.target.value })}
                    placeholder="default (optional)"
                    title="Optional default value used when a researcher leaves this field empty"
                    className="h-8 w-32 rounded-md border border-slate-300 px-2 text-xs"
                  />
                ) : null}
                {row.type === "enum" ? (
                  <input
                    value={row.options}
                    onChange={(event) => patchRow(index, { options: event.target.value })}
                    placeholder="aerobic, HIGH=high"
                    className="h-8 flex-1 rounded-md border border-slate-300 px-2 text-xs"
                  />
                ) : null}
                <button type="button" onClick={() => setRows((current) => current.filter((_, i) => i !== index))} className="rounded-md border border-slate-300 px-2 py-0.5 text-xs text-slate-500">
                  ✕
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={() => setRows((current) => [...current, { key: "", type: "string", container: "single", required: true, options: "", default: "" }])}
              className="w-fit rounded-md border border-slate-300 px-2 py-0.5 text-xs font-semibold text-slate-600"
            >
              + Add field
            </button>
          </div>
          )}

          <div className="flex gap-2">
            <button type="button" onClick={onSave} disabled={busy || !canSave} className="rounded-md bg-cyan-700 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
              Save type
            </button>
            <button type="button" onClick={() => setEditing(false)} className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-600">
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
