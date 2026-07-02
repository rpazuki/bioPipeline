"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  deleteSavedTypedValue,
  listPublishedJobs,
  listSavedTypedValues,
  saveTypedValue,
  updateSavedTypedValue,
} from "@/lib/api";
import ResizableSplitPane from "@/components/pipelines/ResizableSplitPane";
import SavedCasesControl from "@/components/pipelines/SavedCasesControl";
import TypedValueEditor from "@/components/pipelines/TypedValueEditor";
import type { PublishedField, ResolvedType, SavedTypedValue } from "@/types";

// A per-job saved value keys as `job:{publishedJobId}:field:{fieldId}:{type}` (plain
// saveable fields and inline typed fields); a library-type value keys by the type name
// and is reusable across every job that binds that type. Returns the job id or null.
function jobIdOf(typeKey: string): string | null {
  const match = /^job:(.+):field:/.exec(typeKey);
  return match ? match[1] : null;
}

// One "saved type" the researcher sees in the list: all cases sharing a
// `${type_key}::${container}` key. A single-instance type has one case; a
// multi-instance type has several named cases with one default.
interface SavedGroup {
  key: string;
  label: string;
  container: "single" | "list" | "map";
  value_kind: "typed" | "plain";
  multiple: boolean;
  type_key: string;
  type_schema: ResolvedType | null;
  cases: SavedTypedValue[];
}

function caseDefault(cases: SavedTypedValue[]): SavedTypedValue | undefined {
  return cases.find((item) => item.is_default) ?? cases[0];
}

function groupsFrom(items: SavedTypedValue[]): SavedGroup[] {
  const map = new Map<string, SavedGroup>();
  for (const item of items) {
    const key = `${item.type_key}::${item.container}`;
    let group = map.get(key);
    if (!group) {
      group = {
        key,
        label: item.label || item.type_key,
        container: item.container,
        value_kind: item.value_kind,
        multiple: item.multiple,
        type_key: item.type_key,
        type_schema: item.type_schema,
        cases: [],
      };
      map.set(key, group);
    }
    group.cases.push(item);
    group.multiple = group.multiple || item.multiple;
  }
  for (const group of map.values()) {
    group.cases.sort((a, b) => Number(b.is_default) - Number(a.is_default) || a.name.localeCompare(b.name));
  }
  return [...map.values()].sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: "base" }));
}

// A blank starting value for a brand-new case, matching its container shape.
function emptyValue(container: string, schema: ResolvedType | null): unknown {
  if (container === "list") return [];
  if (container === "map") return {};
  return schema?.kind === "scalar" ? "" : {};
}

// Build the minimal PublishedField the structured editor needs from a saved case.
// TypedValueEditor only reads `type_schema` and `container`; the rest satisfy types.
function editorField(item: SavedTypedValue): PublishedField {
  return {
    id: item.id,
    label: item.label,
    type: "typed",
    required: false,
    help: "",
    example: "",
    options: [],
    type_schema: item.type_schema,
    container: item.container,
  };
}

function PlainValueEditor({ item, value, onChange }: { item: SavedTypedValue; value: unknown; onChange: (value: unknown) => void }) {
  const field = item.field_schema;
  const type = field.type ?? "string";
  const options = field.options ?? [];
  const base = "h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950";
  if (type === "boolean") {
    return <input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} className="h-5 w-5" />;
  }
  if (type === "enum") {
    return (
      <select className={base} value={String(value ?? "")} onChange={(event) => {
        const selected = options.find((option) => String(option.value) === event.target.value);
        onChange(selected?.value ?? event.target.value);
      }}>
        {options.map((option) => <option key={option.label} value={String(option.value)}>{option.label}</option>)}
      </select>
    );
  }
  if (type === "text" || type === "object" || type === "json" || type === "list" || type === "multi_enum") {
    const display = value == null ? "" : typeof value === "string" ? value : JSON.stringify(value);
    return <textarea className="min-h-24 rounded-md border border-slate-300 p-3 font-mono text-xs" value={display} onChange={(event) => onChange(event.target.value)} />;
  }
  const inputType = type === "integer" || type === "float" ? "number" : type === "datetime" ? "datetime-local" : "text";
  return <input type={inputType} className={base} value={value == null ? "" : String(value)} onChange={(event) => onChange(event.target.value)} />;
}

export default function SavedValuesPage() {
  const [items, setItems] = useState<SavedTypedValue[]>([]);
  const [drafts, setDrafts] = useState<Record<string, unknown>>({});
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [jobNames, setJobNames] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("Loading your saved values…");
  const [listCollapsed, setListCollapsed] = useState(false);
  const paneWrapRef = useRef<HTMLDivElement>(null);
  const [paneHeight, setPaneHeight] = useState(600);

  // Which published job (if any) a saved value belongs to. Per-job values name it;
  // library-type values are reusable across every job that binds the type.
  function ownerText(typeKey: string): string {
    const jobId = jobIdOf(typeKey);
    if (!jobId) return "Reusable across jobs";
    return jobNames[jobId] ? `Job: ${jobNames[jobId]}` : "Job no longer available";
  }

  const groups = useMemo(() => groupsFrom(items), [items]);
  // `selectedKey`/`selectedCaseId` are user overrides; fall back so a valid group and
  // case are always shown (e.g. after a delete removes the selected one).
  const selectedGroup = groups.find((group) => group.key === selectedKey) ?? groups[0] ?? null;
  const selectedItem = selectedGroup
    ? selectedGroup.cases.find((item) => item.id === selectedCaseId) ?? caseDefault(selectedGroup.cases) ?? null
    : null;

  async function refresh() {
    const next = await listSavedTypedValues();
    setItems(next);
    // Seed the per-case edit drafts from the stored value so the editor opens with the
    // current value rather than a blank.
    setDrafts(Object.fromEntries(next.map((item) => [item.id, item.value])));
    const count = groupsFrom(next).length;
    setStatus(next.length === 0 ? "You have not saved any values yet." : `${count} saved type(s)`);
    return next;
  }

  useEffect(() => {
    refresh().catch((cause: Error) => setError(cause.message));
    // Resolve owning-job names for per-job saved values; failure just omits the name.
    listPublishedJobs()
      .then((jobs) => setJobNames(Object.fromEntries(jobs.map((job) => [job.id, job.name]))))
      .catch(() => {});
  }, []);

  // Size the split panes to fill the viewport below their top (mirrors the researcher
  // published-jobs page) so both boxes share one height and the page doesn't double-scroll.
  useEffect(() => {
    function measure() {
      if (!paneWrapRef.current) return;
      const top = paneWrapRef.current.getBoundingClientRect().top;
      setPaneHeight(Math.max(520, window.innerHeight - top - 16));
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  // Run an action with busy/error handling, then reload.
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  function selectGroup(group: SavedGroup) {
    setSelectedKey(group.key);
    setSelectedCaseId(caseDefault(group.cases)?.id ?? null);
  }

  function saveDraft(item: SavedTypedValue) {
    run(async () => {
      const updated = await updateSavedTypedValue(item.id, { value: drafts[item.id] });
      await refresh();
      setStatus(`Updated ${updated.name || updated.label}`);
    });
  }

  function addCase(group: SavedGroup, name: string) {
    run(async () => {
      const saved = await saveTypedValue({
        type_key: group.type_key,
        container: group.container,
        name,
        make_default: group.cases.length === 0,
        label: group.label,
        type_schema: group.type_schema ?? {},
        value_kind: "typed",
        value: emptyValue(group.container, group.type_schema),
      });
      await refresh();
      setSelectedKey(group.key);
      setSelectedCaseId(saved.id);
      setStatus(`Added case “${name}”`);
    });
  }

  function renameCase(id: string, name: string) {
    run(async () => {
      await updateSavedTypedValue(id, { name });
      await refresh();
      setStatus(`Renamed case to “${name}”`);
    });
  }

  function setDefaultCase(id: string) {
    run(async () => {
      await updateSavedTypedValue(id, { make_default: true });
      await refresh();
      setStatus("Default case updated");
    });
  }

  function deleteCase(group: SavedGroup, item: SavedTypedValue) {
    const label = item.name || item.label || group.label;
    if (!window.confirm(`Delete your saved "${label}" value? Matching job fields will no longer pre-fill it.`)) return;
    run(async () => {
      await deleteSavedTypedValue(item.id);
      const next = await refresh();
      // Keep a sensible selection: the group's remaining default, else the first group.
      const stillThere = groupsFrom(next).find((candidate) => candidate.key === group.key);
      if (stillThere) {
        setSelectedKey(stillThere.key);
        setSelectedCaseId(caseDefault(stillThere.cases)?.id ?? null);
      } else {
        setSelectedKey(null);
        setSelectedCaseId(null);
      }
      setStatus(`Deleted ${label}`);
    });
  }

  return (
    <section className="p-5">
      <div ref={paneWrapRef}>
      <ResizableSplitPane
        defaultSplit={30}
        minLeft={20}
        minRight={30}
        autoHeight
        minHeight={paneHeight}
        collapsed={listCollapsed}
        left={
        listCollapsed ? (
        // Collapsed: a narrow rail with just an expand control, freeing width for the editor.
        <aside className="flex h-full flex-col items-center gap-3 rounded-md border border-slate-200 bg-white p-2">
          <button
            type="button"
            aria-expanded={false}
            aria-label="Expand saved types"
            title={`Show saved types (${groups.length})`}
            onClick={() => setListCollapsed(false)}
            className="rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
          >
            ▸
          </button>
          <span className="text-xs font-semibold text-slate-500" style={{ writingMode: "vertical-rl" }}>
            Saved Values
          </span>
        </aside>
        ) : (
        <aside className="grid content-start gap-3 rounded-md border border-slate-200 bg-white p-4 h-full">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-slate-950">Saved Values</h2>
              <p className="mt-1 text-sm text-slate-500">
                Reusable values for structured and saveable fields. A{" "}
                <span className="font-semibold">multiple</span> type holds several named cases.
              </p>
            </div>
            <button
              type="button"
              aria-expanded
              aria-label="Collapse saved types"
              onClick={() => setListCollapsed(true)}
              className="shrink-0 rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
            >
              ◂ Hide
            </button>
          </div>
          {groups.length === 0 ? (
            <p className="text-sm text-slate-500">
              No saved values yet. Open a published job, fill a saveable field, and click{" "}
              <span className="font-semibold">Save</span>.
            </p>
          ) : (
            <ul className="grid content-start gap-1">
              {groups.map((group) => {
                const active = selectedGroup?.key === group.key;
                return (
                  <li key={group.key}>
                    <button
                      type="button"
                      onClick={() => selectGroup(group)}
                      className={`flex w-full items-center justify-between gap-2 rounded-md border px-3 py-2 text-left text-sm ${active ? "border-cyan-700 bg-cyan-50" : "border-slate-200 hover:bg-slate-50"}`}
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-mono font-semibold text-slate-900">{group.label}</span>
                        <span className="block truncate text-[11px] text-slate-500">{ownerText(group.type_key)}</span>
                        <span className="block text-[11px] text-slate-400">
                          {group.container}
                          {group.multiple ? ` · ${group.cases.length} case(s)` : ""}
                        </span>
                      </span>
                      {group.multiple ? (
                        <span className="shrink-0 rounded-full bg-violet-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-700">multiple</span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </aside>
        )
        }
        right={
        <main className="grid content-start gap-3 rounded-md border border-slate-200 bg-white p-4 h-full">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="truncate text-sm font-semibold text-slate-950">{selectedGroup?.label ?? "Saved value"}</h3>
              <p className="mt-1 truncate text-xs text-slate-500">
                {selectedGroup ? ownerText(selectedGroup.type_key) : "Select a saved type on the left to edit it."}
              </p>
            </div>
            <div className="flex flex-col items-end gap-1 text-right">
              <span className="rounded-md border border-yellow-300 bg-yellow-100 px-2 py-1 text-[11px] text-yellow-800">{status}</span>
              {selectedItem ? <span className="text-[11px] text-slate-400">Updated {selectedItem.updated_at}</span> : null}
            </div>
          </div>
          {error ? <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}

          {selectedGroup && selectedItem ? (
            <div className="grid content-start gap-2">
              {selectedGroup.multiple ? (
                <SavedCasesControl
                  cases={selectedGroup.cases}
                  selectedId={selectedItem.id}
                  onSelect={(id) => setSelectedCaseId(id)}
                  onAdd={(name) => addCase(selectedGroup, name)}
                  onRename={(id, name) => renameCase(id, name)}
                  onSetDefault={(id) => setDefaultCase(id)}
                  onDelete={(id) => {
                    const target = selectedGroup.cases.find((item) => item.id === id);
                    if (target) deleteCase(selectedGroup, target);
                  }}
                  disabled={busy}
                />
              ) : null}

              {selectedItem.value_kind === "plain" ? (
                <PlainValueEditor
                  item={selectedItem}
                  value={drafts[selectedItem.id]}
                  onChange={(value) => setDrafts((current) => ({ ...current, [selectedItem.id]: value }))}
                />
              ) : (
                <TypedValueEditor
                  key={selectedItem.id}
                  field={editorField(selectedItem)}
                  value={drafts[selectedItem.id]}
                  onChange={(value) => setDrafts((current) => ({ ...current, [selectedItem.id]: value }))}
                  columns={selectedGroup.container === "single" ? 1 : 2}
                />
              )}

              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => saveDraft(selectedItem)}
                  className="rounded-md bg-cyan-700 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
                >
                  Save changes
                </button>
                {!selectedGroup.multiple ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => deleteCase(selectedGroup, selectedItem)}
                    className="rounded-md border border-rose-200 px-3 py-1.5 text-xs font-semibold text-rose-700 disabled:opacity-50"
                  >
                    Delete
                  </button>
                ) : null}
              </div>
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              {groups.length === 0 ? "Saved values you create will appear here." : "Select a saved type on the left to edit it."}
            </p>
          )}
        </main>
        }
      />
      </div>
    </section>
  );
}
