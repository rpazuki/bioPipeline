"use client";

import { useRef, useState, type ReactNode } from "react";

import type { PublishedField, ResolvedScalar, ResolvedType, ResolvedTypeField } from "@/types";

// Structured editor for a "typed" published field: renders a defined type as a
// single sub-form, an ordered list (add/remove rows), or a string-keyed map
// (add/remove keyed rows). Recurses for nested typed fields. Produces a native
// object / array / object value — the backend coerces leaf scalars on submit, so
// raw string inputs are fine here.

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asText(value: unknown): string {
  if (value == null) return "";
  return typeof value === "string" ? value : String(value);
}

function LeafInput({
  field,
  value,
  onChange,
}: {
  // A compound type's field node, or a simple type's bare leaf descriptor — both
  // carry the `type`/`options`/`example` this input reads.
  field: ResolvedTypeField | ResolvedScalar;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const base = "h-8 w-full rounded-md border border-slate-300 px-2 text-xs text-slate-950";
  if (field.type === "boolean") {
    return <input type="checkbox" className="h-4 w-4" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} />;
  }
  if (field.type === "enum") {
    return (
      <select
        className={base}
        value={asText(value)}
        onChange={(event) => {
          const option = field.options.find((item) => asText(item.value) === event.target.value);
          onChange(option ? option.value : event.target.value);
        }}
      >
        <option value="">—</option>
        {/* Index-prefixed key: option values can repeat (e.g. an enum whose options were
            not de-duplicated), and a bare value key would collide and crash the render. */}
        {field.options.map((option, index) => (
          <option key={`${index}-${asText(option.value)}`} value={asText(option.value)}>
            {option.label}
          </option>
        ))}
      </select>
    );
  }
  const inputType = field.type === "integer" || field.type === "float" ? "number" : field.type === "datetime" ? "datetime-local" : "text";
  return (
    <input
      type={inputType}
      className={base}
      value={asText(value)}
      placeholder={field.example || ""}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

function ObjectEditor({
  schema,
  value,
  onChange,
}: {
  schema: ResolvedType;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const object = isObject(value) ? value : {};
  const setField = (name: string, next: unknown) => onChange({ ...object, [name]: next });
  return (
    <div className="grid gap-1.5 rounded-md border border-slate-200 bg-white p-2">
      {(schema.fields ?? []).map((field) => (
        <label key={field.name} className="grid gap-1 text-xs text-slate-600">
          <span className="font-medium text-slate-700">
            {field.name}
            {field.required ? <span className="text-rose-500"> *</span> : null}
          </span>
          {field.type === "typed" && field.type_schema ? (
            <ContainerEditor
              schema={field.type_schema}
              container={field.container ?? "single"}
              value={object[field.name]}
              onChange={(next) => setField(field.name, next)}
            />
          ) : field.container === "list" ? (
            // A leaf primitive with a list container (e.g. levels: list[float]) is an
            // add/remove list of bare values, not a single input.
            <ScalarListEditor leaf={field} value={object[field.name]} onChange={(next) => setField(field.name, next)} />
          ) : field.container === "map" ? (
            <ScalarMapEditor leaf={field} value={object[field.name]} onChange={(next) => setField(field.name, next)} />
          ) : (
            <LeafInput field={field} value={object[field.name]} onChange={(next) => setField(field.name, next)} />
          )}
        </label>
      ))}
    </div>
  );
}

function ListEditor({
  schema,
  value,
  onChange,
  columns = 1,
  actions,
}: {
  schema: ResolvedType;
  value: unknown;
  onChange: (value: unknown) => void;
  columns?: 1 | 2;
  actions?: ReactNode;
}) {
  const items = Array.isArray(value) ? value : [];
  return (
    <div className="grid gap-2">
      <div className={`grid max-h-96 gap-2 overflow-y-auto pr-1 ${columns === 2 ? "md:grid-cols-2" : ""}`}>
        {items.map((item, index) => (
          <div key={index} className="grid gap-1 rounded-md border border-slate-200 bg-slate-50 p-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] uppercase tracking-wide text-slate-400">{schema.name} #{index + 1}</span>
              <button
                type="button"
                className="rounded border border-rose-200 px-2 py-0.5 text-[11px] font-semibold text-rose-700"
                onClick={() => onChange(items.filter((_, other) => other !== index))}
              >
                Remove
              </button>
            </div>
            <ObjectEditor schema={schema} value={item} onChange={(next) => onChange(items.map((existing, other) => (other === index ? next : existing)))} />
          </div>
        ))}
      </div>
      {/* The add button and any caller-supplied actions (e.g. a Save button) share one
          row so they sit side by side rather than stacking. */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="w-fit rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-600"
          onClick={() => onChange([...items, {}])}
        >
          + Add {schema.name}
        </button>
        {actions}
      </div>
    </div>
  );
}

interface MapRow {
  id: string;
  key: string;
  value: unknown;
}

function MapEditor({
  schema,
  value,
  onChange,
  columns = 1,
  actions,
}: {
  schema: ResolvedType;
  value: unknown;
  onChange: (value: unknown) => void;
  columns?: 1 | 2;
  actions?: ReactNode;
}) {
  // Stable row ids so editing a key doesn't lose input focus (the map key alone is
  // not a stable identity). Initial ids come from position; the counter (read only in
  // the add handler, never during render) keeps later additions unique.
  const counter = useRef(0);
  const [rows, setRows] = useState<MapRow[]>(() =>
    Object.entries(isObject(value) ? value : {}).map(([key, entry], index) => ({ id: `init-${index}`, key, value: entry })),
  );

  function commit(next: MapRow[]) {
    setRows(next);
    const out: Record<string, unknown> = {};
    for (const row of next) {
      const key = row.key.trim();
      if (key) out[key] = row.value;
    }
    onChange(out);
  }

  const duplicate = (key: string) => key.trim() && rows.filter((row) => row.key.trim() === key.trim()).length > 1;

  return (
    <div className="grid gap-2">
      <div className={`grid max-h-96 gap-2 overflow-y-auto pr-1 ${columns === 2 ? "md:grid-cols-2" : ""}`}>
        {rows.map((row, index) => (
          <div key={row.id} className="grid gap-1 rounded-md border border-slate-200 bg-slate-50 p-2">
            <div className="flex items-center gap-2">
              <input
                className="h-8 flex-1 rounded-md border border-slate-300 px-2 text-xs font-medium text-slate-950"
                placeholder="key (e.g. SLAB)"
                value={row.key}
                onChange={(event) => commit(rows.map((other, position) => (position === index ? { ...other, key: event.target.value } : other)))}
              />
              <button
                type="button"
                className="rounded border border-rose-200 px-2 py-0.5 text-[11px] font-semibold text-rose-700"
                onClick={() => commit(rows.filter((_, position) => position !== index))}
              >
                Remove
              </button>
            </div>
            {duplicate(row.key) ? <span className="text-[11px] text-amber-700">Duplicate key — only the last is kept.</span> : null}
            <ObjectEditor schema={schema} value={row.value} onChange={(next) => commit(rows.map((other, position) => (position === index ? { ...other, value: next } : other)))} />
          </div>
        ))}
      </div>
      {/* The add button and any caller-supplied actions (e.g. a Save button) share one
          row so they sit side by side rather than stacking. */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="w-fit rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-600"
          onClick={() => commit([...rows, { id: `add-${counter.current++}`, key: "", value: {} }])}
        >
          + Add entry
        </button>
        {actions}
      </div>
    </div>
  );
}

// A simple (scalar) type as an ordered list of bare leaf values.
function ScalarListEditor({
  leaf,
  value,
  onChange,
  columns = 1,
  actions,
}: {
  leaf: ResolvedScalar;
  value: unknown;
  onChange: (value: unknown) => void;
  columns?: 1 | 2;
  actions?: ReactNode;
}) {
  const items = Array.isArray(value) ? value : [];
  return (
    <div className="grid gap-2">
      <div className={`grid max-h-96 gap-2 overflow-y-auto pr-1 ${columns === 2 ? "md:grid-cols-2" : ""}`}>
        {items.map((item, index) => (
          <div key={index} className="flex items-center gap-2">
            <LeafInput field={leaf} value={item} onChange={(next) => onChange(items.map((existing, other) => (other === index ? next : existing)))} />
            <button
              type="button"
              className="shrink-0 rounded border border-rose-200 px-2 py-0.5 text-[11px] font-semibold text-rose-700"
              onClick={() => onChange(items.filter((_, other) => other !== index))}
            >
              Remove
            </button>
          </div>
        ))}
        {items.length === 0 ? <span className="text-[11px] text-slate-400">No entries yet.</span> : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="w-fit rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-600"
          onClick={() => onChange([...items, ""])}
        >
          + Add entry
        </button>
        {actions}
      </div>
    </div>
  );
}

// A simple (scalar) type as a string-keyed map of bare leaf values.
function ScalarMapEditor({
  leaf,
  value,
  onChange,
  columns = 1,
  actions,
}: {
  leaf: ResolvedScalar;
  value: unknown;
  onChange: (value: unknown) => void;
  columns?: 1 | 2;
  actions?: ReactNode;
}) {
  // Stable row ids so editing a key doesn't lose input focus (mirrors MapEditor).
  const counter = useRef(0);
  const [rows, setRows] = useState<MapRow[]>(() =>
    Object.entries(isObject(value) ? value : {}).map(([key, entry], index) => ({ id: `init-${index}`, key, value: entry })),
  );

  function commit(next: MapRow[]) {
    setRows(next);
    const out: Record<string, unknown> = {};
    for (const row of next) {
      const key = row.key.trim();
      if (key) out[key] = row.value;
    }
    onChange(out);
  }

  const duplicate = (key: string) => key.trim() && rows.filter((row) => row.key.trim() === key.trim()).length > 1;

  return (
    <div className="grid gap-2">
      <div className={`grid max-h-96 gap-2 overflow-y-auto pr-1 ${columns === 2 ? "md:grid-cols-2" : ""}`}>
        {rows.map((row, index) => (
          <div key={row.id} className="grid gap-1">
            <div className="flex items-center gap-2">
              <input
                className="h-8 w-1/3 rounded-md border border-slate-300 px-2 text-xs font-medium text-slate-950"
                placeholder="key"
                value={row.key}
                onChange={(event) => commit(rows.map((other, position) => (position === index ? { ...other, key: event.target.value } : other)))}
              />
              <LeafInput field={leaf} value={row.value} onChange={(next) => commit(rows.map((other, position) => (position === index ? { ...other, value: next } : other)))} />
              <button
                type="button"
                className="shrink-0 rounded border border-rose-200 px-2 py-0.5 text-[11px] font-semibold text-rose-700"
                onClick={() => commit(rows.filter((_, position) => position !== index))}
              >
                Remove
              </button>
            </div>
            {duplicate(row.key) ? <span className="text-[11px] text-amber-700">Duplicate key — only the last is kept.</span> : null}
          </div>
        ))}
        {rows.length === 0 ? <span className="text-[11px] text-slate-400">No entries yet.</span> : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="w-fit rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-600"
          onClick={() => commit([...rows, { id: `add-${counter.current++}`, key: "", value: "" }])}
        >
          + Add entry
        </button>
        {actions}
      </div>
    </div>
  );
}

function ContainerEditor({
  schema,
  container,
  value,
  onChange,
  columns = 1,
  actions,
}: {
  schema: ResolvedType;
  container: "single" | "list" | "map";
  value: unknown;
  onChange: (value: unknown) => void;
  columns?: 1 | 2;
  actions?: ReactNode;
}) {
  // A simple (scalar) type edits a bare leaf value (single), or a list/map of them.
  if (schema.kind === "scalar" && schema.scalar) {
    const leaf = schema.scalar;
    if (container === "list") return <ScalarListEditor leaf={leaf} value={value} onChange={onChange} columns={columns} actions={actions} />;
    if (container === "map") return <ScalarMapEditor leaf={leaf} value={value} onChange={onChange} columns={columns} actions={actions} />;
    const single = <LeafInput field={leaf} value={value} onChange={onChange} />;
    if (!actions) return single;
    return (
      <div className="grid gap-2">
        {single}
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      </div>
    );
  }
  if (container === "list") return <ListEditor schema={schema} value={value} onChange={onChange} columns={columns} actions={actions} />;
  if (container === "map") return <MapEditor schema={schema} value={value} onChange={onChange} columns={columns} actions={actions} />;
  // A single object has no add button to align against, so any actions render on their
  // own row below the editor.
  if (!actions) return <ObjectEditor schema={schema} value={value} onChange={onChange} />;
  return (
    <div className="grid gap-2">
      <ObjectEditor schema={schema} value={value} onChange={onChange} />
      <div className="flex flex-wrap items-center gap-2">{actions}</div>
    </div>
  );
}

export default function TypedValueEditor({
  field,
  value,
  onChange,
  columns = 1,
  actions,
}: {
  field: PublishedField;
  value: unknown;
  onChange: (value: unknown) => void;
  // List/map containers lay their entries out in this many columns (the Saved
  // Values page uses 2 to show two records per row).
  columns?: 1 | 2;
  // Optional controls (e.g. a Save button) rendered alongside the editor's own add
  // button so they sit on one aligned action row.
  actions?: ReactNode;
}) {
  if (!field.type_schema) {
    // No resolved schema (e.g. its library type was deleted) — fall back to JSON so
    // the value is still editable rather than silently uneditable.
    return (
      <textarea
        className="min-h-24 rounded-md border border-slate-300 p-2 font-mono text-xs"
        value={typeof value === "string" ? value : JSON.stringify(value, null, 2)}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }
  return <ContainerEditor schema={field.type_schema} container={field.container ?? "single"} value={value} onChange={onChange} columns={columns} actions={actions} />;
}
