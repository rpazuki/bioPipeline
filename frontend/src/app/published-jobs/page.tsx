"use client";

import { useEffect, useRef, useState } from "react";

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
function typedFieldKey(field: PublishedField): string | null {
  if (field.type !== "typed") return null;
  const typeKey = (field.schema_ref || field.type_schema?.name || "").trim();
  if (!typeKey) return null;
  return `${typeKey}::${field.container ?? "single"}`;
}

type SharedSelection = { root: string; path: string; name: string };

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
}: {
  field: PublishedField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const base = "h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950";
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
      }}>
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
    return <TypedValueEditor field={field} value={value} onChange={onChange} />;
  }
  if (field.type === "text" || field.type === "object" || field.type === "json" || field.type === "list") {
    return <textarea className="min-h-24 rounded-md border border-slate-300 p-3 font-mono text-xs" value={asInputValue(value)} onChange={(event) => onChange(event.target.value)} />;
  }
  const inputType = field.type === "integer" || field.type === "float" ? "number" : field.type === "datetime" ? "datetime-local" : "text";
  return <input type={inputType} className={base} value={asInputValue(value)} placeholder={field.placeholder || field.example} onChange={(event) => onChange(event.target.value)} />;
}

function InputFieldControl({
  field,
  files,
  sharedSel,
  onPickFiles,
  onOpenBrowser,
  onClearShared,
}: {
  field: PublishedField;
  files: File[];
  sharedSel: SharedSelection | null;
  onPickFiles: (files: File[]) => void;
  onOpenBrowser: () => void;
  onClearShared: () => void;
}) {
  const sources = field.sources ?? [];
  const canUpload = sources.includes("upload");
  const canShared = sources.includes("shared");
  const isDirectory = field.accept === "directory";
  return (
    <span className="grid gap-1.5">
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
  const [filterText, setFilterText] = useState("");
  const [selected, setSelected] = useState<PublishedJobPublicDetail | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  // Researcher's reusable saved typed values, keyed by `${type_key}::${container}`.
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
  const paneWrapRef = useRef<HTMLDivElement>(null);
  const [paneHeight, setPaneHeight] = useState(600);

  async function refresh() {
    setJobs(await listPublishedJobs());
  }

  async function refreshSavedTyped() {
    const items = await listSavedTypedValues();
    setSavedTyped(Object.fromEntries(items.map((item) => [`${item.type_key}::${item.container}`, item])));
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
    refreshSavedTyped().catch(() => {});
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

  async function selectJob(id: string) {
    const job = await getPublishedJob(id);
    setError(null); // a stale error from a previous job must not linger on the new one
    setSelected(job);
    // Start from each field's default, then pre-fill any typed field that has a
    // matching saved value so the researcher edits their last value, not a blank.
    const initial = Object.fromEntries(job.fields.map((field) => [field.id, defaultValue(field)]));
    for (const field of job.fields) {
      const key = typedFieldKey(field);
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

  async function saveTypedField(field: PublishedField) {
    const typeKey = (field.schema_ref || field.type_schema?.name || "").trim();
    if (!typeKey) return;
    const container = field.container ?? "single";
    const saved = await saveTypedValue({
      type_key: typeKey,
      container,
      label: typeKey,
      type_schema: field.type_schema ?? null,
      value: values[field.id],
    });
    setSavedTyped((current) => ({ ...current, [`${typeKey}::${container}`]: saved }));
    setStatus(`Saved your ${typeKey} value`);
  }

  return (
    <section className="p-5">
      <div ref={paneWrapRef} style={{ height: paneHeight }}>
      <ResizableSplitPane
        defaultSplit={50}
        minLeft={20}
        minRight={30}
        className="h-full"
        left={
        <aside className="grid content-start gap-3 rounded-md border border-slate-200 bg-white p-4 h-full">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">Published Jobs</h2>
          <p className="mt-1 text-sm text-slate-500">Run admin-published workflows without seeing job or pipeline YAML.</p>
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
            <span className="mt-1 block text-xs text-slate-500 whitespace-pre-line">{job.description || `Version ${job.version}`}</span>
          </button>
        ))}
      </aside>
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
            <div className="grid gap-3 md:grid-cols-2">
              {selected.fields.map((field) => {
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
                        files={files[field.id] ?? []}
                        sharedSel={shared[field.id] ?? null}
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
                        <FieldInput field={field} value={values[field.id]} onChange={(value) => setValues((current) => ({ ...current, [field.id]: value }))} />
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() => saveTypedField(field).catch((cause: Error) => setError(cause.message))}
                            className="w-fit rounded-md border border-cyan-300 bg-cyan-50 px-2.5 py-1 text-xs font-semibold text-cyan-800 hover:bg-cyan-100"
                          >
                            Save
                          </button>
                          {typedFieldKey(field) && savedTyped[typedFieldKey(field) as string] ? (
                            <span className="text-[11px] font-normal text-emerald-700">
                              Your saved value is loaded — edit and Save to update it.
                            </span>
                          ) : (
                            <span className="text-[11px] font-normal text-slate-400">
                              Save to reuse this value across jobs that use this type.
                            </span>
                          )}
                        </div>
                      </div>
                    ) : (
                      <FieldInput field={field} value={values[field.id]} onChange={(value) => setValues((current) => ({ ...current, [field.id]: value }))} />
                    )}
                  </>
                );
                const className = "grid gap-1 text-xs font-semibold text-slate-600";
                // A typed field renders a multi-control sub-form; a <label> would route
                // every click to its first control, so wrap those in a <div> instead.
                return field.type === "typed" && (field.io_role ?? "none") === "none" ? (
                  <div key={field.id} className={className}>{inner}</div>
                ) : (
                  <label key={field.id} className={className}>{inner}</label>
                );
              })}
              <label className="grid gap-1 text-xs font-semibold text-slate-600">
                <span className="flex items-center gap-2">
                  {repeat ? "First run at" : "Run at"}
                  <FieldHelp field={{ id: "scheduled_at", label: "Run at", type: "datetime", required: false, help: "Optional time to queue the run for later execution.", example: "2026-06-07T18:30", options: [] }} />
                </span>
                <input className="h-9 rounded-md border border-slate-300 px-3 text-sm" type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} />
              </label>
            </div>
            {/* Recurring schedule controls */}
            <div className="grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
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
              <span className="w-fit rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">{status}</span>
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
