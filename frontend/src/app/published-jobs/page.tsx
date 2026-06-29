"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  browseSharedRoot,
  createDraftRun,
  createRecurringSchedule,
  getPublishedJob,
  listJobSharedRoots,
  listPublishedJobs,
  listSavedTypedValues,
  saveTypedValue,
  submitPublishedJobRun,
  uploadRunInput,
  type RunFileBinding,
} from "@/lib/api";
import ResizableSplitPane from "@/components/pipelines/ResizableSplitPane";
import TypedValueEditor from "@/components/pipelines/TypedValueEditor";
import type { PublishedField, PublishedJobPublicDetail, PublishedJobPublicSummary, RecurrenceEndMode, RecurrenceUnit, SavedTypedValue, SharedEntry, SharedRootInfo } from "@/types";

// A typed field's reusable identity: its library type name (or inline schema name)
// plus container shape. Saved values are keyed by this, so the same value pre-fills
// any published job whose typed field uses the same type + container.
function savedFieldIdentity(field: PublishedField, publishedJobId: string): { typeKey: string; container: "single" | "list" | "map" } | null {
  if (field.type === "typed") {
    const typeKey = (field.schema_ref || field.type_schema?.name || "").trim();
    return typeKey ? { typeKey, container: field.container ?? "single" } : null;
  }
  if (field.saveable && (field.io_role ?? "none") === "none") {
    return { typeKey: `job:${publishedJobId}:field:${field.id}:${field.type}`, container: "single" };
  }
  return null;
}

function savedFieldKey(field: PublishedField, publishedJobId: string): string | null {
  const identity = savedFieldIdentity(field, publishedJobId);
  return identity ? `${identity.typeKey}::${identity.container}` : null;
}

function savedMapFrom(items: SavedTypedValue[]): Record<string, SavedTypedValue> {
  return Object.fromEntries(items.map((item) => [`${item.type_key}::${item.container}`, item]));
}

type SharedSelection = { root: string; path: string; name: string };

// The in-progress run form, persisted to sessionStorage so leaving this page (e.g. to
// peek at My Runs) and coming back keeps the selected job and everything typed into it,
// rather than resetting to a blank form. Scoped to the tab session: it clears when the
// tab closes. Picked upload files are deliberately absent — the browser does not allow
// re-creating a File handle from storage, so those must be re-picked after a navigation.
const FORM_STATE_KEY = "published-jobs:run-form";

type FormSnapshot = {
  jobId: string;
  values: Record<string, unknown>;
  shared: Record<string, SharedSelection>;
  scheduledAt: string;
  repeat: boolean;
  everyN: number;
  unit: RecurrenceUnit;
  endsMode: RecurrenceEndMode;
  endsCount: number;
  endsAt: string;
  // For each field that pre-fills from a saved value: that value's `updated_at` at
  // snapshot time. On restore we compare it with the current saved value — if it changed
  // (the researcher edited it on the Saved Values page) the new value wins; otherwise the
  // snapshot value wins, preserving an in-progress edit.
  savedBaseline: Record<string, string>;
};

function defaultValue(field: PublishedField) {
  // A typed field holds a native object/array the structured editor manages. Its
  // admin-set `default` may be a scalar (e.g. the type's name) that is NOT a valid
  // value for the container — submitting it verbatim fails coercion ("must be a
  // map/list of …"). So accept the default only when it already matches the
  // container shape; otherwise start with an empty container. This must run before
  // the generic default branch below, which would otherwise return that scalar.
  if (field.type === "typed") {
    const preset = field.default;
    if (field.container === "list") return Array.isArray(preset) ? preset : [];
    if (field.container === "map") return preset && typeof preset === "object" && !Array.isArray(preset) ? preset : {};
    // single: a simple (scalar) type holds a bare value, so start it empty (or its
    // scalar default); a compound type holds an object the structured editor manages.
    if (field.type_schema?.kind === "scalar") {
      return preset != null && typeof preset !== "object" ? preset : "";
    }
    return preset && typeof preset === "object" && !Array.isArray(preset) ? preset : {};
  }
  // A $WILL_PROVIDE$ placeholder is not a real default — start the field empty so
  // the researcher fills it in rather than submitting the placeholder verbatim.
  if (field.default !== undefined && field.default !== null && !String(field.default).includes("$WILL_PROVIDE$")) {
    return field.default;
  }
  if (field.type === "boolean") return false;
  if (field.type === "multi_enum" || field.type === "list") return [];
  if (field.type === "object" || field.type === "json") return "{}";
  return "";
}

function asInputValue(value: unknown): string {
  if (value == null) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

// The catalog list shows only the first non-empty line of a job's description so a
// long multi-line blurb doesn't blow out the row height.
function firstLine(text: string | undefined | null): string {
  if (!text) return "";
  return text.split("\n").map((line) => line.trim()).find((line) => line.length > 0) ?? "";
}

function FieldHelp({ field }: { field: PublishedField }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  return (
    <span ref={ref} className="relative inline-flex">
      <button
        type="button"
        aria-label={`About ${field.label}`}
        className="grid h-5 w-5 place-items-center rounded-full border border-slate-300 text-xs font-bold text-slate-600 hover:bg-slate-50"
        onClick={() => setOpen((value) => !value)}
      >
        ?
      </button>
      {open ? (
        <span className="absolute left-6 top-0 z-20 grid w-72 gap-2 rounded-md border border-slate-200 bg-white p-3 text-xs text-slate-600 shadow-lg">
          <span className="font-semibold text-slate-900">{field.label}</span>
          <span>{field.help || "This value customizes the published job before execution."}</span>
          <span className="rounded-md bg-slate-50 px-2 py-1 font-mono text-[11px] text-slate-700">
            Example: {field.example || asInputValue(field.default) || "value"}
          </span>
        </span>
      ) : null}
    </span>
  );
}

function readonlyText(field: PublishedField, value: unknown): string {
  if (field.type === "boolean") return value ? "Yes" : "No";
  if (field.type === "enum") {
    const option = field.options.find((item) => item.value === value || String(item.value) === String(value));
    return option ? option.label : asInputValue(value);
  }
  if (field.type === "multi_enum" && Array.isArray(value)) {
    const labels = value.map((v) => {
      const option = field.options.find((item) => item.value === v || String(item.value) === String(v));
      return option ? option.label : String(v);
    });
    return labels.join(", ") || "—";
  }
  if (field.type === "typed") {
    return value == null ? "—" : JSON.stringify(value);
  }
  return asInputValue(value) || "—";
}

function FieldInput({
  field,
  value,
  onChange,
  actions,
}: {
  field: PublishedField;
  value: unknown;
  onChange: (value: unknown) => void;
  // Forwarded to the typed editor so a Save button can sit beside its add-entry button.
  actions?: ReactNode;
}) {
  const base = "h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950";
  const autoComplete = field.autoompelete ? "on" : "off";
  if (field.readonly) {
    return <span className="flex h-9 items-center text-sm text-slate-800">{readonlyText(field, value)}</span>;
  }
  if (field.type === "boolean") {
    return <input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} className="h-5 w-5" />;
  }
  if (field.type === "enum") {
    return (
      <select className={base} value={asInputValue(value)} onChange={(event) => {
        const option = field.options.find((item) => asInputValue(item.value) === event.target.value);
        onChange(option?.value ?? event.target.value);
      }} autoComplete={autoComplete}>
        {field.options.map((option) => (
          <option key={option.label} value={asInputValue(option.value)}>
            {option.label}
          </option>
        ))}
      </select>
    );
  }
  if (field.type === "multi_enum") {
    const values = Array.isArray(value) ? value.map(asInputValue) : [];
    return (
      <div className="flex flex-wrap gap-2">
        {field.options.map((option) => {
          const optionValue = asInputValue(option.value);
          return (
            <label key={option.label} className="flex items-center gap-1.5 rounded-md border border-slate-200 px-2 py-1 text-xs">
              <input
                type="checkbox"
                checked={values.includes(optionValue)}
                onChange={(event) => {
                  const next = event.target.checked ? [...values, optionValue] : values.filter((item) => item !== optionValue);
                  onChange(field.options.filter((item) => next.includes(asInputValue(item.value))).map((item) => item.value));
                }}
              />
              {option.label}
            </label>
          );
        })}
      </div>
    );
  }
  if (field.type === "typed" && field.type_schema) {
    return <TypedValueEditor field={field} value={value} onChange={onChange} actions={actions} />;
  }
  if (field.type === "text" || field.type === "object" || field.type === "json" || field.type === "list") {
    return <textarea className="min-h-24 rounded-md border border-slate-300 p-3 font-mono text-xs" value={asInputValue(value)} autoComplete={autoComplete} onChange={(event) => onChange(event.target.value)} />;
  }
  const inputType = field.type === "integer" || field.type === "float" ? "number" : field.type === "datetime" ? "datetime-local" : field.type === "url" ? "url" : "text";
  return <input type={inputType} className={base} value={asInputValue(value)} autoComplete={autoComplete} placeholder={field.placeholder || field.example} onChange={(event) => onChange(event.target.value)} />;
}

function InputFieldControl({
  field,
  value,
  files,
  sharedSel,
  onChange,
  onPickFiles,
  onOpenBrowser,
  onClearShared,
}: {
  field: PublishedField;
  value: unknown;
  files: File[];
  sharedSel: SharedSelection | null;
  onChange: (value: unknown) => void;
  onPickFiles: (files: File[]) => void;
  onOpenBrowser: () => void;
  onClearShared: () => void;
}) {
  const sources = field.sources ?? [];
  const canUpload = sources.includes("upload");
  const canShared = sources.includes("shared");
  const isDirectory = field.accept === "directory";
  const base = "h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950";
  const autoComplete = field.autoompelete ? "on" : "off";
  return (
    <span className="grid gap-1.5">
      {field.type === "url" ? (
        <input
          type="url"
          className={base}
          value={asInputValue(value)}
          autoComplete={autoComplete}
          placeholder={field.placeholder || field.example || "https://example.org/data.csv"}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : null}
      {canUpload ? (
        <span className="flex flex-wrap items-center gap-2">
          {isDirectory ? (
            <label className="cursor-pointer rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
              Choose Folder
              <input
                type="file"
                multiple
                {...({ webkitdirectory: "" } as Record<string, string>)}
                className="sr-only"
                onChange={(event) => onPickFiles(Array.from(event.target.files ?? []))}
              />
            </label>
          ) : (
            <label className="cursor-pointer rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
              Choose File
              <input
                type="file"
                className="sr-only"
                onChange={(event) => onPickFiles(event.target.files?.[0] ? [event.target.files[0]] : [])}
              />
            </label>
          )}
          {files.length ? (
            <span className="text-xs font-normal text-emerald-700">{isDirectory ? `${files.length} files` : files[0].name}</span>
          ) : null}
        </span>
      ) : null}
      {canShared ? (
        <span className="flex flex-wrap items-center gap-2">
          <button type="button" className="w-fit rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold" onClick={onOpenBrowser}>
            Choose from shared storage
          </button>
          {sharedSel ? (
            <span className="text-xs font-normal text-emerald-700">
              {sharedSel.name}{" "}
              <button type="button" className="text-slate-400 underline" onClick={onClearShared}>
                clear
              </button>
            </span>
          ) : null}
        </span>
      ) : null}
      {!canUpload && !canShared ? <span className="text-xs font-normal text-amber-700">No input source is enabled for this field.</span> : null}
    </span>
  );
}

function SharedBrowser({
  jobId,
  field,
  roots,
  onSelect,
  onClose,
}: {
  jobId: string;
  field: PublishedField;
  roots: SharedRootInfo[];
  onSelect: (selection: SharedSelection) => void;
  onClose: () => void;
}) {
  const fieldRoots = roots.filter((root) => (field.shared_roots ?? []).includes(root.id));
  const [rootId, setRootId] = useState(fieldRoots[0]?.id ?? "");
  const [subpath, setSubpath] = useState("");
  const [entries, setEntries] = useState<SharedEntry[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!rootId) return;
    browseSharedRoot(jobId, field.id, rootId, subpath)
      .then((result) => {
        setEntries(result.entries);
        setErr(null);
      })
      .catch((cause: Error) => setErr(cause.message));
  }, [jobId, field.id, rootId, subpath]);

  const parent = subpath.includes("/") ? subpath.slice(0, subpath.lastIndexOf("/")) : "";
  const rootLabel = fieldRoots.find((root) => root.id === rootId)?.label ?? rootId;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-4" onClick={onClose}>
      <div className="grid max-h-[80vh] w-full max-w-lg gap-3 overflow-hidden rounded-md border border-slate-200 bg-white p-4" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-semibold text-slate-900">Choose from shared storage</h4>
          <button type="button" onClick={onClose} className="text-slate-400">
            ✕
          </button>
        </div>
        {fieldRoots.length > 1 ? (
          <select className="h-8 rounded-md border border-slate-300 px-2 text-xs" value={rootId} onChange={(event) => { setRootId(event.target.value); setSubpath(""); }}>
            {fieldRoots.map((root) => (
              <option key={root.id} value={root.id}>
                {root.label}
              </option>
            ))}
          </select>
        ) : (
          <p className="text-xs text-slate-500">{rootLabel}</p>
        )}
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span className="font-mono">/{subpath}</span>
          {subpath ? (
            <button type="button" className="underline" onClick={() => setSubpath(parent)}>
              up
            </button>
          ) : null}
          {field.accept === "directory" ? (
            <button type="button" className="ml-auto rounded bg-cyan-700 px-2 py-1 text-white" onClick={() => onSelect({ root: rootId, path: subpath, name: subpath || rootLabel })}>
              Select this folder
            </button>
          ) : null}
        </div>
        {err ? <p className="text-xs text-rose-700">{err}</p> : null}
        <ul className="grid gap-1 overflow-auto">
          {entries.map((entry) => {
            const selectable = (entry.kind === "file" && field.accept === "file") || (entry.kind === "directory" && field.accept === "directory");
            return (
              <li key={entry.path} className="flex items-center justify-between gap-2 rounded border border-slate-100 px-2 py-1 text-xs">
                <span className="flex items-center gap-2">
                  <span>{entry.kind === "directory" ? "📁" : "📄"}</span>
                  {entry.kind === "directory" ? (
                    <button type="button" className="font-semibold text-slate-800 underline" onClick={() => setSubpath(entry.path)}>
                      {entry.name}
                    </button>
                  ) : (
                    <span>{entry.name}</span>
                  )}
                </span>
                {selectable ? (
                  <button type="button" className="rounded bg-cyan-700 px-2 py-0.5 text-white" onClick={() => onSelect({ root: rootId, path: entry.path, name: entry.name })}>
                    Select
                  </button>
                ) : null}
              </li>
            );
          })}
          {entries.length === 0 && !err ? <li className="text-xs text-slate-400">Empty folder</li> : null}
        </ul>
      </div>
    </div>
  );
}

function OutputFieldHint({ field }: { field: PublishedField }) {
  const channels = field.delivery ?? [];
  const label = channels.includes("download") ? "Result returned to you (download)" : "Result returned to you";
  return (
    <span className="flex h-9 items-center">
      <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-normal text-slate-600">{label}</span>
    </span>
  );
}

export default function PublishedJobsPage() {
  const [jobs, setJobs] = useState<PublishedJobPublicSummary[]>([]);
  const [jobsCollapsed, setJobsCollapsed] = useState(false);
  const [filterText, setFilterText] = useState("");
  const [selected, setSelected] = useState<PublishedJobPublicDetail | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  // Researcher's reusable field values, keyed by `${type_key}::${container}`.
  const [savedTyped, setSavedTyped] = useState<Record<string, SavedTypedValue>>({});
  const [files, setFiles] = useState<Record<string, File[]>>({});
  const [shared, setShared] = useState<Record<string, SharedSelection>>({});
  const [sharedRoots, setSharedRoots] = useState<SharedRootInfo[]>([]);
  const [browseField, setBrowseField] = useState<PublishedField | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [scheduledAt, setScheduledAt] = useState("");
  // Recurring-schedule controls (off by default — a plain run otherwise).
  const [repeat, setRepeat] = useState(false);
  const [everyN, setEveryN] = useState(1);
  const [unit, setUnit] = useState<RecurrenceUnit>("days");
  const [endsMode, setEndsMode] = useState<RecurrenceEndMode>("never");
  const [endsCount, setEndsCount] = useState(10);
  const [endsAt, setEndsAt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("Choose a published job");
  // Gate the persistence writer until the saved form (if any) has been restored, so the
  // initial empty state never overwrites a snapshot before we read it back.
  const [hydrated, setHydrated] = useState(false);
  const paneWrapRef = useRef<HTMLDivElement>(null);
  const [paneHeight, setPaneHeight] = useState(600);

  async function refresh() {
    setJobs(await listPublishedJobs());
  }

  async function refreshSavedTyped() {
    const items = await listSavedTypedValues();
    setSavedTyped(savedMapFrom(items));
  }

  const normalizedFilter = filterText.trim().toLowerCase();
  const visibleJobs = [...jobs]
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }))
    .filter((job) => {
      if (!normalizedFilter) return true;
      const haystack = `${job.name}\n${job.description ?? ""}`.toLowerCase();
      return haystack.includes(normalizedFilter);
    });

  useEffect(() => {
    refresh().catch((cause: Error) => setError(cause.message));
    // Saved values are loaded in the restore effect below (it needs them to reconcile a
    // restored form against any value edited on the Saved Values page).
  }, []);

  useEffect(() => {
    function measure() {
      if (!paneWrapRef.current) return;
      const top = paneWrapRef.current.getBoundingClientRect().top;
      setPaneHeight(Math.max(800, window.innerHeight - top - 16));
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  // Restore an in-progress form when returning to this page. Runs once on mount; falls
  // back to a clean slate if there is no snapshot or the saved job is gone/unreadable.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Load the current saved values first: they back the typed/saveable field pre-fills,
      // and a restored form must reflect any value edited on the Saved Values page.
      let savedItems: SavedTypedValue[] = [];
      try {
        savedItems = (await listSavedTypedValues()) ?? [];
      } catch {
        savedItems = [];
      }
      if (cancelled) return;
      const savedMap = savedMapFrom(savedItems);
      setSavedTyped(savedMap);

      const raw = window.sessionStorage.getItem(FORM_STATE_KEY);
      let snapshot: FormSnapshot | null = null;
      try {
        snapshot = raw ? (JSON.parse(raw) as FormSnapshot) : null;
      } catch {
        snapshot = null;
      }
      if (!snapshot?.jobId) {
        setHydrated(true);
        return;
      }

      let job: PublishedJobPublicDetail | null = null;
      try {
        job = await getPublishedJob(snapshot.jobId);
      } catch {
        job = null; // job no longer published — start fresh
      }
      if (cancelled) return;
      if (!job) {
        setHydrated(true);
        return;
      }

      // Start from the snapshot, then let any saved value that CHANGED since the snapshot
      // override its field — so editing a saved value propagates here, while an untouched
      // saved value keeps the researcher's in-progress edit.
      const restored: Record<string, unknown> = { ...(snapshot.values ?? {}) };
      for (const field of job.fields) {
        const key = savedFieldKey(field, job.id);
        const saved = key ? savedMap[key] : undefined;
        if (!saved || saved.value == null) continue;
        if (saved.updated_at !== snapshot.savedBaseline?.[field.id]) {
          restored[field.id] = saved.value;
        }
      }
      setSelected(job);
      setValues(restored);
      setShared(snapshot.shared ?? {});
      setScheduledAt(snapshot.scheduledAt ?? "");
      setRepeat(snapshot.repeat ?? false);
      setEveryN(snapshot.everyN ?? 1);
      setUnit(snapshot.unit ?? "days");
      setEndsMode(snapshot.endsMode ?? "never");
      setEndsCount(snapshot.endsCount ?? 10);
      setEndsAt(snapshot.endsAt ?? "");
      setStatus(`Selected ${job.name}`);
      const hasShared = job.fields.some((field) => (field.sources ?? []).includes("shared"));
      if (hasShared) {
        try {
          const roots = await listJobSharedRoots(job.id);
          if (!cancelled) setSharedRoots(roots);
        } catch { /* leave shared roots empty */ }
      }
      if (!cancelled) setHydrated(true);
    })();
    return () => { cancelled = true; };
  }, []);

  // Persist the form on every change (after hydration). Clears the snapshot when no job
  // is selected so a stale form never resurfaces.
  useEffect(() => {
    if (!hydrated) return;
    if (!selected) {
      window.sessionStorage.removeItem(FORM_STATE_KEY);
      return;
    }
    // Record the saved value each pre-fillable field is tracking, so a later restore can
    // tell whether the researcher changed it on the Saved Values page meanwhile.
    const savedBaseline: Record<string, string> = {};
    for (const field of selected.fields) {
      const key = savedFieldKey(field, selected.id);
      const saved = key ? savedTyped[key] : undefined;
      if (saved) savedBaseline[field.id] = saved.updated_at;
    }
    const snapshot: FormSnapshot = {
      jobId: selected.id,
      values,
      shared,
      scheduledAt,
      repeat,
      everyN,
      unit,
      endsMode,
      endsCount,
      endsAt,
      savedBaseline,
    };
    window.sessionStorage.setItem(FORM_STATE_KEY, JSON.stringify(snapshot));
  }, [hydrated, selected, values, shared, scheduledAt, repeat, everyN, unit, endsMode, endsCount, endsAt, savedTyped]);

  async function selectJob(id: string) {
    const job = await getPublishedJob(id);
    setError(null); // a stale error from a previous job must not linger on the new one
    setSelected(job);
    // Start from each field's default, then pre-fill any typed field that has a
    // matching saved value so the researcher edits their last value, not a blank.
    const initial = Object.fromEntries(job.fields.map((field) => [field.id, defaultValue(field)]));
    for (const field of job.fields) {
      const key = savedFieldKey(field, job.id);
      const saved = key ? savedTyped[key] : undefined;
      if (saved && saved.value != null) initial[field.id] = saved.value;
    }
    setValues(initial);
    setFiles({});
    setShared({});
    setBrowseField(null);
    setWorkspaceId(null);
    const hasShared = job.fields.some((field) => (field.sources ?? []).includes("shared"));
    setSharedRoots(hasShared ? await listJobSharedRoots(id) : []);
    setStatus(`Selected ${job.name}`);
  }

  async function submit() {
    if (!selected) return;
    setError(null);
    const fields = selected.fields;
    const willUpload = fields.some((field) => field.io_role === "input" && !shared[field.id] && (files[field.id]?.length ?? 0) > 0);
    const needsWorkspace = fields.some((field) => field.io_role === "output") || willUpload;
    let wsId = workspaceId;
    if (needsWorkspace && !wsId) {
      wsId = (await createDraftRun(selected.id)).workspace_id;
      setWorkspaceId(wsId);
    }
    const fileBindings: Record<string, RunFileBinding> = {};
    for (const field of fields) {
      if (field.io_role !== "input") continue;
      const sharedSel = shared[field.id];
      if (sharedSel) {
        fileBindings[field.id] = { kind: "shared", root: sharedSel.root, path: sharedSel.path };
        continue;
      }
      const picked = files[field.id] ?? [];
      if (!picked.length || !(field.sources ?? []).includes("upload") || !wsId) continue;
      if (field.accept === "directory") {
        for (const member of picked) {
          const relpath = member.webkitRelativePath ? member.webkitRelativePath.split("/").slice(1).join("/") || member.name : member.name;
          setStatus(`Uploading ${relpath}…`);
          await uploadRunInput(selected.id, wsId, field.id, member, relpath);
        }
        fileBindings[field.id] = { kind: "upload", path: "" };
      } else {
        const file = picked[0];
        setStatus(`Uploading ${file.name}…`);
        const uploaded = await uploadRunInput(selected.id, wsId, field.id, file);
        fileBindings[field.id] = { kind: "upload", path: uploaded.handle };
      }
    }
    if (repeat) {
      setStatus("Creating schedule…");
      const schedule = await createRecurringSchedule(selected.id, {
        values,
        file_bindings: fileBindings,
        workspace_id: wsId,
        every_n: everyN,
        unit,
        ends_mode: endsMode,
        ends_count: endsCount,
        ends_at: endsMode === "until" ? endsAt || null : null,
        start_at: scheduledAt || null,
      });
      setStatus(`Recurring schedule created — every ${schedule.every_n} ${schedule.unit}`);
      // The schedule's workspace is now its input template; drop the local handle so a
      // later plain run makes its own.
      setWorkspaceId(null);
      return;
    }
    setStatus("Submitting…");
    const run = await submitPublishedJobRun(selected.id, values, scheduledAt || null, { workspaceId: wsId, fileBindings });
    setStatus(`Submitted run ${run.id}`);
    // The backend persists each typed field's value on execute; reflect that here so
    // the "saved" hints update without a reload.
    refreshSavedTyped().catch(() => {});
    // Each execution gets a fresh workspace, so drop the spent workspace id. Keep
    // the file/shared selections, though: a researcher often re-runs the same job
    // with a tweaked option (e.g. a different averaging method) and the same data.
    // Clearing them stranded the inputs — the next submit reported the field empty
    // even after the file was re-picked (re-selecting the same file fires no change
    // event). The selections re-upload into the new workspace on the next submit.
    setWorkspaceId(null);
  }

  async function saveField(field: PublishedField) {
    if (!selected) return;
    const identity = savedFieldIdentity(field, selected.id);
    if (!identity) return;
    const { typeKey, container } = identity;
    const saved = await saveTypedValue({
      type_key: typeKey,
      container,
      label: field.label || typeKey,
      type_schema: field.type_schema ?? {},
      value_kind: field.type === "typed" ? "typed" : "plain",
      field_schema: field.type === "typed" ? {} : field,
      value: values[field.id],
    });
    setSavedTyped((current) => ({ ...current, [`${typeKey}::${container}`]: saved }));
    setStatus(`Saved your ${field.label} value`);
  }

  // Render one published field as a keyed form node. Extracted from the JSX so the
  // fields can be distributed across two independent columns below.
  function renderFieldNode(field: PublishedField) {
    // Persist-this-typed-value button + its hint, shared between the two typed layouts
    // below (inline beside an editor's add button, or on its own footer row).
    const saveButton = (
      <button
        type="button"
        onClick={() => saveField(field).catch((cause: Error) => setError(cause.message))}
        className="w-fit rounded-md border border-cyan-300 bg-cyan-50 px-2.5 py-1 text-xs font-semibold text-cyan-800 hover:bg-cyan-100"
      >
        Save
      </button>
    );
    const saveKey = selected ? savedFieldKey(field, selected.id) : null;
    const saveHint = saveKey && savedTyped[saveKey] ? (
      <span className="text-[11px] font-normal text-emerald-700">
        Your saved value is loaded — edit and Save to update it.
      </span>
    ) : (
      <span className="text-[11px] font-normal text-slate-400">
        {field.type === "typed"
          ? "Save to reuse this value across jobs that use this type."
          : "Save to reuse this value when you run this published job again."}
      </span>
    );
    // Map/list editors render an "+ Add entry" button the Save button can ride beside;
    // a single object has none, so its Save stays on its own row.
    const inlineSave = field.container === "list" || field.container === "map";
    const inner = (
      <>
        <span className="flex items-center gap-2">
          {field.label}
          <FieldHelp field={field} />
        </span>
        {field.io_role === "output" ? (
          <OutputFieldHint field={field} />
        ) : field.io_role === "input" ? (
          <InputFieldControl
            field={field}
            value={values[field.id]}
            files={files[field.id] ?? []}
            sharedSel={shared[field.id] ?? null}
            onChange={(value) => setValues((current) => ({ ...current, [field.id]: value }))}
            onPickFiles={(picked) => setFiles((current) => ({ ...current, [field.id]: picked }))}
            onOpenBrowser={() => setBrowseField(field)}
            onClearShared={() => setShared((current) => {
              const next = { ...current };
              delete next[field.id];
              return next;
            })}
          />
        ) : field.type === "typed" ? (
          <div className="grid gap-1.5">
            <FieldInput
              field={field}
              value={values[field.id]}
              onChange={(value) => setValues((current) => ({ ...current, [field.id]: value }))}
              actions={inlineSave ? saveButton : undefined}
            />
            {inlineSave ? (
              saveHint
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                {saveButton}
                {saveHint}
              </div>
            )}
          </div>
        ) : field.saveable ? (
          <div className="grid gap-1.5">
            <FieldInput field={field} value={values[field.id]} onChange={(value) => setValues((current) => ({ ...current, [field.id]: value }))} />
            <div className="flex flex-wrap items-center gap-2">{saveButton}{saveHint}</div>
          </div>
        ) : (
          <FieldInput field={field} value={values[field.id]} onChange={(value) => setValues((current) => ({ ...current, [field.id]: value }))} />
        )}
      </>
    );
    const className = "grid gap-1 text-xs font-semibold text-slate-600";
    // A typed field renders a multi-control sub-form; a <label> would route
    // every click to its first control, so wrap those in a <div> instead.
    return (field.type === "typed" || field.saveable) && (field.io_role ?? "none") === "none" ? (
      <div key={field.id} className={className}>{inner}</div>
    ) : (
      <label key={field.id} className={className}>{inner}</label>
    );
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
        collapsed={jobsCollapsed}
        left={
        jobsCollapsed ? (
        // Collapsed: a narrow rail with just an expand control, so the form panel
        // beside it gains the freed width.
        <aside className="flex h-full flex-col items-center gap-3 rounded-md border border-slate-200 bg-white p-2">
          <button
            type="button"
            aria-expanded={false}
            aria-label="Expand published jobs"
            title={`Show published jobs (${jobs.length})`}
            onClick={() => setJobsCollapsed(false)}
            className="rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
          >
            ▸
          </button>
          <span className="text-xs font-semibold text-slate-500" style={{ writingMode: "vertical-rl" }}>
            Published Jobs
          </span>
        </aside>
        ) : (
        <aside className="grid content-start gap-3 rounded-md border border-slate-200 bg-white p-4 h-full">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Published Jobs</h2>
            <p className="mt-1 text-sm text-slate-500">Run admin-published workflows without seeing job or pipeline YAML.</p>
          </div>
          <button
            type="button"
            aria-expanded
            aria-label="Collapse published jobs"
            onClick={() => setJobsCollapsed(true)}
            className="shrink-0 rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
          >
            ◂ Hide
          </button>
        </div>
        <label className="grid gap-1 text-xs font-semibold text-slate-600">
          Filter jobs
          <input
            type="text"
            value={filterText}
            onChange={(event) => setFilterText(event.target.value)}
            placeholder="Search by name or description"
            className="h-9 rounded-md border border-slate-300 px-3 text-sm font-normal text-slate-900"
          />
        </label>
        {jobs.length === 0 ? <p className="text-sm text-slate-500">No jobs have been published yet.</p> : null}
        {jobs.length > 0 && visibleJobs.length === 0 ? <p className="text-sm text-slate-500">No jobs match your filter.</p> : null}
        {visibleJobs.map((job) => (
          <button
            key={job.id}
            type="button"
            className={`rounded-md border px-3 py-2 text-left ${selected?.id === job.id ? "border-cyan-700 bg-cyan-50" : "border-slate-200 hover:bg-slate-50"}`}
            onClick={() => selectJob(job.id).catch((cause: Error) => setError(cause.message))}
          >
            <span className="block text-sm font-semibold text-slate-950">{job.name}</span>
            <span className="mt-1 block truncate text-xs text-slate-500">{firstLine(job.description) || `Version ${job.version}`}</span>
          </button>
        ))}
      </aside>
        )
        }
        right={
        <main className="grid content-start gap-3 rounded-md border border-slate-200 bg-white p-4 h-full">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-950">{selected?.name ?? "Job Form"}</h3>
            <p className="mt-1 text-xs text-slate-500 whitespace-pre-line">{selected?.description ?? status}</p>
          </div>
        </div>
        {selected ? (
          <div className="grid gap-4">
            {(() => {
              // Lay the fields out in three independent columns instead of a row-coupled
              // grid. In a `grid-cols-3` grid each row is as tall as its tallest cell, so
              // a short field (a checkbox) sitting beside a tall typed field was stretched
              // to match it, leaving a badly shaped gap. Here each column is its own
              // vertical stack, so every field takes only the height it needs. Fields fill
              // the left column top-to-bottom first, then the middle, then the right —
              // which preserves the published field order, and keeps that order when the
              // columns collapse to one on narrow screens. ("Run at" lives in the schedule
              // box below.)
              const elements = selected.fields.map(renderFieldNode);
              const perColumn = Math.ceil(elements.length / 3);
              return (
                <div className="grid items-start gap-4 md:grid-cols-3">
                  <div className="grid content-start gap-3">{elements.slice(0, perColumn)}</div>
                  <div className="grid content-start gap-3">{elements.slice(perColumn, perColumn * 2)}</div>
                  <div className="grid content-start gap-3">{elements.slice(perColumn * 2)}</div>
                </div>
              );
            })()}
            {/* Scheduling: when to (first) run, plus optional recurrence */}
            <div className="grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
              <label className="grid gap-1 font-semibold text-slate-700">
                <span className="flex items-center gap-2">
                  {repeat ? "First run at" : "Run at"}
                  <FieldHelp field={{ id: "scheduled_at", label: "Run at", type: "datetime", required: false, help: "Optional time to queue the run for later execution.", example: "2026-06-07T18:30", options: [] }} />
                </span>
                <input className="h-9 w-full rounded-md border border-slate-300 px-3 text-sm font-normal text-slate-900" type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} />
              </label>
              <label className="flex items-center gap-2 font-semibold text-slate-700">
                <input type="checkbox" checked={repeat} onChange={(event) => setRepeat(event.target.checked)} />
                Repeat on a schedule
              </label>
              {repeat ? (
                <div className="grid gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span>Every</span>
                    <input
                      type="number"
                      min={1}
                      value={everyN}
                      onChange={(event) => setEveryN(Math.max(1, Number(event.target.value) || 1))}
                      className="h-8 w-16 rounded-md border border-slate-300 px-2"
                    />
                    <select value={unit} onChange={(event) => setUnit(event.target.value as RecurrenceUnit)} className="h-8 rounded-md border border-slate-300 px-2">
                      <option value="minutes">minutes</option>
                      <option value="hours">hours</option>
                      <option value="days">days</option>
                      <option value="weeks">weeks</option>
                    </select>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span>Ends</span>
                    <select value={endsMode} onChange={(event) => setEndsMode(event.target.value as RecurrenceEndMode)} className="h-8 rounded-md border border-slate-300 px-2">
                      <option value="never">never</option>
                      <option value="count">after N runs</option>
                      <option value="until">on date</option>
                    </select>
                    {endsMode === "count" ? (
                      <input
                        type="number"
                        min={1}
                        value={endsCount}
                        onChange={(event) => setEndsCount(Math.max(1, Number(event.target.value) || 1))}
                        className="h-8 w-20 rounded-md border border-slate-300 px-2"
                      />
                    ) : null}
                    {endsMode === "until" ? (
                      <input type="datetime-local" value={endsAt} onChange={(event) => setEndsAt(event.target.value)} className="h-8 rounded-md border border-slate-300 px-2" />
                    ) : null}
                  </div>
                  <span className="text-[11px] text-slate-400">
                    The first run uses “First run at” above (or now if blank), then repeats. Uploaded inputs are kept and reused each time.
                  </span>
                </div>
              ) : null}
            </div>
            <div className="grid gap-2">
              <button type="button" className="w-fit rounded-md bg-cyan-700 px-4 py-2 text-sm font-semibold text-white" onClick={() => submit().catch((cause: Error) => setError(cause.message))}>
                {repeat ? "Create recurring schedule" : "Execute Job"}
              </button>
              <span className="w-fit rounded-md border border-yellow-300 bg-yellow-100 px-3 py-2 text-xs text-yellow-800">{status}</span>
              {error ? <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}
            </div>
          </div>
        ) : (
          <p className="text-sm text-slate-500">Select a published job to fill its fields and execute it.</p>
        )}
      </main>
        }
      />
      </div>
      {browseField && selected ? (
        <SharedBrowser
          jobId={selected.id}
          field={browseField}
          roots={sharedRoots}
          onSelect={(selection) => {
            setShared((current) => ({ ...current, [browseField.id]: selection }));
            setBrowseField(null);
          }}
          onClose={() => setBrowseField(null)}
        />
      ) : null}
    </section>
  );
}
