"use client";

import { useEffect, useState } from "react";

import { deleteSavedTypedValue, listSavedTypedValues, updateSavedTypedValue } from "@/lib/api";
import TypedValueEditor from "@/components/pipelines/TypedValueEditor";
import type { PublishedField, SavedTypedValue } from "@/types";

// Build the minimal PublishedField the structured editor needs from a saved value.
// TypedValueEditor only reads `type_schema` and `container`; the rest satisfy types.
function editorField(saved: SavedTypedValue): PublishedField {
  return {
    id: saved.id,
    label: saved.label,
    type: "typed",
    required: false,
    help: "",
    example: "",
    options: [],
    type_schema: saved.type_schema,
    container: saved.container,
  };
}

export default function SavedValuesPage() {
  const [items, setItems] = useState<SavedTypedValue[]>([]);
  const [drafts, setDrafts] = useState<Record<string, unknown>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("Loading your saved values…");

  async function refresh() {
    const next = await listSavedTypedValues();
    setItems(next);
    // Seed the per-item edit drafts from the stored value so the editor opens with
    // the current value rather than a blank.
    setDrafts(Object.fromEntries(next.map((item) => [item.id, item.value])));
    setStatus(next.length === 0 ? "You have not saved any values yet." : `${next.length} saved value(s)`);
  }

  useEffect(() => {
    refresh().catch((cause: Error) => setError(cause.message));
  }, []);

  async function save(item: SavedTypedValue) {
    setBusyId(item.id);
    setError(null);
    try {
      const updated = await updateSavedTypedValue(item.id, { value: drafts[item.id] });
      setItems((current) => current.map((existing) => (existing.id === item.id ? updated : existing)));
      setStatus(`Updated ${item.label}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusyId(null);
    }
  }

  async function remove(item: SavedTypedValue) {
    if (!window.confirm(`Delete your saved "${item.label}" value? Jobs using this type will no longer pre-fill it.`)) return;
    setBusyId(item.id);
    setError(null);
    try {
      await deleteSavedTypedValue(item.id);
      setStatus(`Deleted ${item.label}`);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="grid gap-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">Saved Values</h2>
          <p className="mt-1 text-sm text-slate-500">
            Reusable values for structured (typed) fields. Each is shared across every published job whose
            field uses the same type, so editing one here updates it everywhere.
          </p>
        </div>
        <span className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">{status}</span>
      </div>
      {error ? <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}

      {items.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 bg-white px-4 py-6 text-sm text-slate-500">
          No saved values yet. Open a published job, fill a typed field, and click <span className="font-semibold">Save</span>.
        </p>
      ) : null}

      <div className="grid gap-3">
        {items.map((item) => (
          <div key={item.id} className="grid gap-2 rounded-md border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-semibold text-slate-900">{item.type_key}</span>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                  {item.container}
                </span>
              </div>
              <span className="text-[11px] text-slate-400">Updated {item.updated_at}</span>
            </div>
            <TypedValueEditor
              field={editorField(item)}
              value={drafts[item.id]}
              onChange={(value) => setDrafts((current) => ({ ...current, [item.id]: value }))}
              // List/map saved values show two records per row for a denser overview.
              columns={item.container === "single" ? 1 : 2}
            />
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busyId === item.id}
                onClick={() => save(item)}
                className="rounded-md bg-cyan-700 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
              >
                Save changes
              </button>
              <button
                type="button"
                disabled={busyId === item.id}
                onClick={() => remove(item)}
                className="rounded-md border border-rose-200 px-3 py-1.5 text-xs font-semibold text-rose-700 disabled:opacity-50"
              >
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
