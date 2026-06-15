"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  archivePublishedJob,
  createPublishedJob,
  deletePublishedJob,
  getAdminPublishedJob,
  getSavedDefinition,
  inspectPublishedJob,
  listAdminPublishedJobRuns,
  listAdminPublishedJobs,
  listAdminPublishedRuns,
  listAdminSharedRoots,
  listSavedDefinitions,
  listTypeLibrary,
  publishPublishedJob,
  updatePublishedJob,
  validatePublishedJob,
} from "@/lib/api";
import ResizableSplitPane from "@/components/pipelines/ResizableSplitPane";
import type { DefinitionSummary, PublishedField, PublishedFieldIoRole, PublishedJobAdmin, PublishedRunSummary, SharedRootInfo, TypeDef } from "@/types";

// Placeholder marking a value a researcher supplies at run time. Each one must
// be exposed (selected) as an input field so the researcher can fill it in.
// Keep in sync with PROVIDED_LATER in bio_pipeline_manager/job_definition.py.
const PROVIDED_LATER = "$WILL_PROVIDE$";

function hasPlaceholder(value: unknown): boolean {
  if (value == null) return false;
  return (typeof value === "string" ? value : JSON.stringify(value)).includes(PROVIDED_LATER);
}

function stringifyValue(value: unknown): string {
  if (value == null) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

// A stable, definition-derived description of what a candidate field maps to,
// derived from its binding (not its label). Shown read-only so an admin can still
// tell which field is which after renaming the label researchers see.
function fieldOrigin(field: PublishedField): string {
  const binding = field.bindings?.[0];
  if (!binding) return field.id;
  if (binding.target === "definition_path") {
    const path = binding.path ?? [];
    if (path[0] === "variables") return `Variable: ${path[1]}`;
    if (path[0] === "defaults") return `Default: ${path[1]}`;
    if (path[0] === "stages") return `${path[1]}: ${path.slice(2).join(".")}`;
    return path.join(".") || field.id;
  }
  if (binding.target === "stage_input_source") return `${binding.stage}: input ${binding.input}`;
  if (binding.target === "stage_input_arg") return `${binding.stage}: input ${binding.input}.${binding.parameter}`;
  if (binding.target === "stage_process_arg") return `${binding.stage}: ${binding.process}.${binding.parameter}`;
  if (binding.target === "stage_output_path") return `${binding.stage}: output ${binding.output}`;
  return field.id;
}

function toggleChannel(list: string[] | undefined, value: string, on: boolean): string[] {
  const set = new Set(list ?? []);
  if (on) set.add(value);
  else set.delete(value);
  return Array.from(set);
}

function statusClasses(status: string): string {
  switch (status) {
    case "succeeded":
      return "bg-emerald-100 text-emerald-800";
    case "running":
      return "bg-cyan-100 text-cyan-800";
    case "failed":
    case "partially_failed":
      return "bg-rose-100 text-rose-800";
    case "blocked":
    case "cancelled":
      return "bg-amber-100 text-amber-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

// Attributes the admin curates in the editor. Everything else (type, default,
// options, bindings) is *derived from the definition* and must track it, so a
// saved field can never pin a stale structure (e.g. enum options captured before
// a variant gained a {variant.group_cols} field).
const CURATED_FIELD_KEYS = [
  "label",
  "help",
  "example",
  "readonly",
  "io_role",
  "accept",
  "sources",
  "delivery",
  "shared_roots",
  // The structured-type binding the admin chose. `type_schema` itself is derived
  // (the backend re-resolves it from the library on save), so it is not curated.
  "schema_ref",
  "container",
] as const;

function mergeFields(candidates: PublishedField[], existing: PublishedField[]) {
  const byId = new Map(candidates.map((field) => [field.id, field]));
  const idByBinding = new Map(candidates.map((field) => [JSON.stringify(field.bindings ?? []), field.id]));
  for (const saved of existing) {
    const targetId = idByBinding.get(JSON.stringify(saved.bindings ?? [])) ?? saved.id;
    const candidate = byId.get(targetId);
    if (!candidate) {
      // No matching candidate in the current definition — keep the saved field as-is.
      byId.set(targetId, { ...saved, id: targetId });
      continue;
    }
    // Fresh structure from the candidate; overlay only the admin-curated attributes.
    const curated: Record<string, unknown> = {};
    for (const key of CURATED_FIELD_KEYS) {
      if (saved[key] !== undefined) curated[key] = saved[key];
    }
    const next = { ...candidate, ...curated, id: targetId };
    // A curated schema_ref means the admin bound this field to a library type; keep it
    // typed even though the fresh candidate's inferred type is a plain primitive.
    if (next.schema_ref) next.type = "typed";
    byId.set(targetId, next);
  }
  return Array.from(byId.values());
}

function selectedFieldIds(existing: PublishedField[], merged: PublishedField[]) {
  const idByBinding = new Map(merged.map((field) => [JSON.stringify(field.bindings ?? []), field.id]));
  return new Set(existing.map((field) => idByBinding.get(JSON.stringify(field.bindings ?? [])) ?? field.id));
}

export default function PublishedJobsAdminPage() {
  const [definitions, setDefinitions] = useState<DefinitionSummary[]>([]);
  const [published, setPublished] = useState<PublishedJobAdmin[]>([]);
  const [allRuns, setAllRuns] = useState<PublishedRunSummary[]>([]);
  const [availableRoots, setAvailableRoots] = useState<SharedRootInfo[]>([]);
  const [libraryTypes, setLibraryTypes] = useState<TypeDef[]>([]);
  const [selectedRuns, setSelectedRuns] = useState<PublishedRunSummary[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [definitionContent, setDefinitionContent] = useState("");
  const [definitionName, setDefinitionName] = useState("");
  const [candidates, setCandidates] = useState<PublishedField[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [fieldOrder, setFieldOrder] = useState<string[]>([]);
  const [fieldEdits, setFieldEdits] = useState<Record<string, PublishedField>>({});
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const paneWrapRef = useRef<HTMLDivElement>(null);
  const [paneHeight, setPaneHeight] = useState(600);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("Ready");

  const selectedFields = useMemo(() => {
    const byId = new Map(candidates.map((field) => [field.id, fieldEdits[field.id] ?? field]));
    return fieldOrder
      .filter((id) => selectedIds.has(id))
      .map((id) => byId.get(id))
      .filter((f): f is PublishedField => f !== undefined);
  }, [candidates, fieldEdits, selectedIds, fieldOrder]);
  // Placeholder values still needing exposure: a $WILL_PROVIDE$ candidate the
  // admin hasn't selected as a field yet. Selecting it clears the warning.
  const placeholderWarnings = useMemo(() => {
    const unexposed = candidates.filter((field) => hasPlaceholder(field.default) && !selectedIds.has(field.id));
    if (!unexposed.length) return [] as string[];
    return [
      `Select these placeholder value(s) as input fields so a researcher can provide them: ${unexposed
        .map((field) => field.label)
        .join(", ")}.`,
    ];
  }, [candidates, selectedIds]);
  const runCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const run of allRuns) counts[run.published_job_id] = (counts[run.published_job_id] ?? 0) + 1;
    return counts;
  }, [allRuns]);

  const orderedCandidates = useMemo(() => {
    const selectedInOrder = fieldOrder
      .filter((id) => selectedIds.has(id))
      .map((id) => candidates.find((c) => c.id === id))
      .filter((f): f is PublishedField => f !== undefined);
    const unselected = candidates.filter((c) => !selectedIds.has(c.id));
    return [...selectedInOrder, ...unselected];
  }, [candidates, fieldOrder, selectedIds]);

  async function refresh() {
    const [defs, jobs, runs, roots, types] = await Promise.all([
      listSavedDefinitions(),
      listAdminPublishedJobs(),
      listAdminPublishedRuns(),
      listAdminSharedRoots().catch(() => [] as SharedRootInfo[]),
      listTypeLibrary().then((result) => result.types).catch(() => [] as TypeDef[]),
    ]);
    setDefinitions(defs);
    setPublished(jobs);
    setAllRuns(runs);
    setAvailableRoots(roots);
    setLibraryTypes(types);
  }

  useEffect(() => {
    refresh().catch((cause: Error) => setError(cause.message));
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

  function clearEditor() {
    setEditingId(null);
    setName("");
    setDescription("");
    setDefinitionName("");
    setDefinitionContent("");
    setCandidates([]);
    setSelectedIds(new Set());
    setFieldOrder([]);
    setFieldEdits({});
    setSelectedRuns([]);
    setWarnings([]);
    setStatus("New published job");
  }

  async function loadSourceDefinition(nameToLoad = definitionName) {
    if (!nameToLoad) return;
    setError(null);
    const document = await getSavedDefinition(nameToLoad);
    setDefinitionName(document.name);
    setDefinitionContent(document.content);
    setName((current) => current || document.job || document.name.replace(/\.(yaml|yml)$/i, ""));
    // Auto-inspect the freshly loaded definition so its fields populate and a
    // default selection is made — otherwise Save Draft stays disabled until the
    // user separately clicks "Inspect Fields", which is easy to miss.
    await inspect({ content: document.content });
    setStatus(`Loaded source definition ${document.name}`);
  }

  async function inspect({ content }: { content?: string } = {}) {
    setError(null);
    const source = content ?? definitionContent;
    const result = await inspectPublishedJob(source);
    setWarnings(result.warnings ?? []);
    const merged = mergeFields(result.candidates, selectedFields);
    const nextEdits = Object.fromEntries(merged.map((field) => [field.id, field]));
    setCandidates(merged);
    setName((current) => current || result.job_name);
    setFieldEdits(nextEdits);
    // Do not auto-select any fields — the admin chooses which to expose. Keep
    // only fields they had already ticked (so re-inspecting after a YAML edit
    // doesn't wipe their choices); never tick anything on their behalf.
    const mergedIds = new Set(merged.map((field) => field.id));
    const survivingIds = new Set(selectedFields.map((field) => field.id).filter((id) => mergedIds.has(id)));
    setSelectedIds(survivingIds);
    // Preserve the order of fields that survived re-inspect; drop those that vanished.
    setFieldOrder((prev) => prev.filter((id) => survivingIds.has(id)));
    setStatus(`Valid definition · ${result.candidates.length} definable fields`);
  }

  async function loadExisting(jobId: string) {
    setError(null);
    const [job, runs] = await Promise.all([getAdminPublishedJob(jobId), listAdminPublishedJobRuns(jobId)]);
    let merged = job.fields;
    try {
      const inspected = await inspectPublishedJob(job.definition_content);
      merged = mergeFields(inspected.candidates, job.fields);
      setWarnings(inspected.warnings ?? []);
    } catch {
      merged = job.fields;
      setWarnings([]);
    }
    setEditingId(job.id);
    setName(job.name);
    setDescription(job.description);
    setDefinitionName(job.definition_name);
    setDefinitionContent(job.definition_content);
    setCandidates(merged);
    const ids = selectedFieldIds(job.fields, merged);
    setSelectedIds(ids);
    // Restore the saved field order; any extra candidates are not selected so won't appear.
    setFieldOrder(job.fields.map((f) => f.id));
    setFieldEdits(Object.fromEntries(merged.map((field) => [field.id, field])));
    setSelectedRuns(runs);
    setStatus(`Editing ${job.name} · ${job.status} · v${job.version}`);
  }

  function toggleField(field: PublishedField) {
    const adding = !selectedIds.has(field.id);
    setSelectedIds((current) => {
      const next = new Set(current);
      if (adding) next.add(field.id);
      else next.delete(field.id);
      return next;
    });
    setFieldOrder((current) =>
      adding ? [...current, field.id] : current.filter((id) => id !== field.id),
    );
    setFieldEdits((current) => ({ ...current, [field.id]: current[field.id] ?? field }));
  }

  function patchField(fieldId: string, patch: Partial<PublishedField>) {
    setFieldEdits((current) => ({ ...current, [fieldId]: { ...current[fieldId], ...patch } }));
  }

  // Reorder a selected field within the selected set. `fieldOrder` only ever holds
  // selected ids, so "bottom" lands after the last *selected* field (not after the
  // unselected candidates listed below them).
  function moveField(fieldId: string, where: "top" | "up" | "down" | "bottom") {
    setFieldOrder((prev) => {
      const idx = prev.indexOf(fieldId);
      if (idx === -1) return prev;
      const next = prev.filter((id) => id !== fieldId);
      const target =
        where === "top"
          ? 0
          : where === "bottom"
            ? next.length
            : where === "up"
              ? Math.max(0, idx - 1)
              : Math.min(next.length, idx + 1);
      next.splice(target, 0, fieldId);
      return next;
    });
  }

  async function save(publishNow: boolean) {
    setError(null);
    const payload = {
      name,
      description,
      definition_name: definitionName,
      definition_content: definitionContent,
      fields: selectedFields,
    };
    const job = editingId
      ? await updatePublishedJob(editingId, payload)
      : await createPublishedJob({ ...payload, status: publishNow ? "published" : "draft" });
    const finalJob = publishNow ? await publishPublishedJob(job.id) : job;
    setStatus(`${publishNow ? "Published" : "Saved"} ${finalJob.name}`);
    await refresh();
    await loadExisting(finalJob.id);
  }

  async function validateCurrent() {
    if (editingId) {
      const result = await validatePublishedJob(editingId);
      setWarnings(result.warnings ?? []);
      setStatus(
        `Saved version is valid · ${result.field_count} public fields · ${result.candidate_count} candidates · ${result.run_count} runs`,
      );
      return;
    }
    await inspect();
  }

  async function archiveCurrent(jobId: string) {
    const job = await archivePublishedJob(jobId);
    setStatus(`Archived ${job.name}`);
    await refresh();
    if (editingId === jobId) await loadExisting(jobId);
  }

  async function duplicateCurrent(jobId: string) {
    const job = await getAdminPublishedJob(jobId);
    const newName = window.prompt("Duplicate as:", `Copy of ${job.name}`);
    if (!newName) return;
    const newJob = await createPublishedJob({
      name: newName.trim(),
      description: job.description,
      definition_name: job.definition_name,
      definition_content: job.definition_content,
      fields: job.fields,
      status: "draft",
    });
    setStatus(`Duplicated as ${newJob.name}`);
    await refresh();
    await loadExisting(newJob.id);
  }

  async function deleteCurrent(jobId: string) {
    const count = runCounts[jobId] ?? 0;
    const force = count > 0;
    const message = force
      ? `Delete this published job and ${count} run link${count === 1 ? "" : "s"}? Underlying queued job records remain.`
      : "Delete this published job?";
    if (!window.confirm(message)) return;
    await deletePublishedJob(jobId, force);
    setStatus("Deleted published job");
    clearEditor();
    await refresh();
  }

  return (
    <section className="grid gap-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">Published Jobs Admin</h2>
          <p className="mt-1 text-sm text-slate-500">Create, edit, validate, publish, archive, and monitor user-facing job forms.</p>
        </div>
      </div>

      {error ? <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}

      <div ref={paneWrapRef} style={{ height: paneHeight }}>
      <ResizableSplitPane
        defaultSplit={55}
        className="h-full"
        left={
        <section className="grid content-start gap-3 rounded-md border border-slate-200 bg-white p-4 h-full overflow-auto">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-slate-950">{editingId ? "Edit Published Job" : "New Published Job"}</h3>
            <button type="button" className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold" onClick={clearEditor}>
              New
            </button>
          </div>
          <div className="grid gap-3">
            <label className="grid gap-1 text-xs font-semibold text-slate-600">
              Published name
              <input className="h-9 rounded-md border border-slate-300 px-3 text-sm" value={name} onChange={(event) => setName(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-semibold text-slate-600">
              Source definition
              <span className="flex gap-2">
                <select className="h-9 min-w-0 flex-1 rounded-md border border-slate-300 px-3 text-sm" value={definitionName} onChange={(event) => setDefinitionName(event.target.value)}>
                  <option value="">Choose saved definition</option>
                  {definitions.map((definition) => (
                    <option key={definition.name} value={definition.name}>
                      {definition.name}
                    </option>
                  ))}
                </select>
                <button type="button" className="rounded-md border border-slate-300 px-3 text-xs font-semibold" onClick={() => loadSourceDefinition().catch((cause: Error) => setError(cause.message))}>
                  Load
                </button>
              </span>
            </label>
            <label className="grid gap-1 text-xs font-semibold text-slate-600">
              Description
              <textarea className="min-h-[4.5rem] resize-y rounded-md border border-slate-300 px-3 py-2 text-sm" value={description} onChange={(event) => setDescription(event.target.value)} />
            </label>
          </div>
          <label className="grid gap-1 text-xs font-semibold text-slate-600">
            Job Definition YAML
            <textarea className="min-h-80 rounded-md border border-slate-300 p-3 font-mono text-xs" value={definitionContent} onChange={(event) => setDefinitionContent(event.target.value)} spellCheck={false} />
          </label>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold" onClick={() => inspect().catch((cause: Error) => setError(cause.message))}>
              Inspect Fields
            </button>
            <button type="button" className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold" disabled={!definitionContent} onClick={() => validateCurrent().catch((cause: Error) => setError(cause.message))}>
              Validate
            </button>
            <button type="button" className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50" disabled={!name || !definitionContent} onClick={() => save(false).catch((cause: Error) => setError(cause.message))}>
              {editingId ? "Update Draft" : "Save Draft"}
            </button>
            <button type="button" className="rounded-md bg-emerald-700 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={!selectedFields.length || !name} onClick={() => save(true).catch((cause: Error) => setError(cause.message))}>
              Publish
            </button>
            {editingId ? (
              <>
                <button type="button" className="rounded-md border border-amber-300 px-3 py-2 text-sm font-semibold text-amber-800" onClick={() => archiveCurrent(editingId).catch((cause: Error) => setError(cause.message))}>
                  Archive
                </button>
                <button type="button" className="rounded-md border border-rose-200 px-3 py-2 text-sm font-semibold text-rose-700" onClick={() => deleteCurrent(editingId).catch((cause: Error) => setError(cause.message))}>
                  Delete
                </button>
              </>
            ) : null}
          </div>
          <span className="w-fit rounded-md border border-yellow-300 bg-yellow-100 px-3 py-2 text-xs text-yellow-800">{status}</span>
          {warnings.length || placeholderWarnings.length ? (
            <div className="grid gap-1 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {[...warnings, ...placeholderWarnings].map((warning, index) => (
                <p key={index}>⚠ {warning}</p>
              ))}
            </div>
          ) : null}
        </section>
        }
        right={
        <section className="flex h-full flex-col gap-3 rounded-md border border-slate-200 bg-white p-4">
          <h3 className="text-sm font-semibold text-slate-950">Definable Fields</h3>
          {candidates.length === 0 ? <p className="text-sm text-slate-500">Load or inspect a Job Definition to choose public fields.</p> : null}
          <div className="grid min-h-0 flex-1 content-start gap-2 overflow-auto pr-1">
            {orderedCandidates.map((field) => {
              const edit = fieldEdits[field.id] ?? field;
              const selected = selectedIds.has(field.id);
              const orderPos = fieldOrder.indexOf(field.id);
              const isFirst = orderPos <= 0;
              const isLast = orderPos === fieldOrder.length - 1;
              return (
                <div
                  key={field.id}
                  onDragOver={selected ? (e) => { e.preventDefault(); setDragOverId(field.id); } : undefined}
                  onDrop={selected ? () => {
                    if (!draggingId || draggingId === field.id) return;
                    setFieldOrder((prev) => {
                      const next = [...prev];
                      const from = next.indexOf(draggingId);
                      const to = next.indexOf(field.id);
                      if (from === -1 || to === -1) return prev;
                      next.splice(from, 1);
                      next.splice(to, 0, draggingId);
                      return next;
                    });
                    setDraggingId(null);
                    setDragOverId(null);
                  } : undefined}
                  className={`grid gap-2 rounded-md border p-3 ${
                    selected && draggingId === field.id
                      ? "border-slate-200 opacity-40"
                      : selected && dragOverId === field.id
                        ? "border-cyan-400 bg-cyan-50"
                        : "border-slate-200"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <label className="flex min-w-0 flex-1 items-center gap-2 text-sm font-semibold text-slate-900">
                      <span
                        draggable={selected}
                        onDragStart={selected ? () => setDraggingId(field.id) : undefined}
                        onDragEnd={selected ? () => { setDraggingId(null); setDragOverId(null); } : undefined}
                        onClick={(e) => e.stopPropagation()}
                        className={`shrink-0 select-none ${selected ? "cursor-grab text-slate-300 active:cursor-grabbing" : "cursor-default text-slate-200"}`}
                        aria-hidden
                      >
                        <svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor">
                          <circle cx="3" cy="2" r="1.5" /><circle cx="7" cy="2" r="1.5" />
                          <circle cx="3" cy="7" r="1.5" /><circle cx="7" cy="7" r="1.5" />
                          <circle cx="3" cy="12" r="1.5" /><circle cx="7" cy="12" r="1.5" />
                        </svg>
                      </span>
                      <input type="checkbox" checked={selected} onChange={() => toggleField(field)} />
                      <span className="truncate font-mono text-xs text-slate-700">{fieldOrigin(field)}</span>
                      <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">{field.type}</span>
                    </label>
                    {selected ? (
                      <span className="flex shrink-0 items-center gap-0.5 text-slate-300">
                        <ReorderButton title="Move to bottom" disabled={isLast} onClick={() => moveField(field.id, "bottom")} variant="bottom" />
                        <ReorderButton title="Move down" disabled={isLast} onClick={() => moveField(field.id, "down")} variant="down" />
                        <ReorderButton title="Move up" disabled={isFirst} onClick={() => moveField(field.id, "up")} variant="up" />
                        <ReorderButton title="Move to top" disabled={isFirst} onClick={() => moveField(field.id, "top")} variant="top" />
                      </span>
                    ) : null}
                  </div>
                  {selected ? (
                    <div className="grid gap-2">
                      <label className="grid gap-1 text-xs text-slate-600">
                        Label researchers see
                        <input className="h-8 rounded-md border border-slate-300 px-2 text-xs" value={edit.label} onChange={(event) => patchField(field.id, { label: event.target.value })} placeholder={fieldOrigin(field)} />
                      </label>
                      <label className="grid gap-1 text-xs text-slate-600">
                        Help text
                        <input className="h-8 rounded-md border border-slate-300 px-2 text-xs" value={edit.help} onChange={(event) => patchField(field.id, { help: event.target.value })} />
                      </label>
                      <label className="grid gap-1 text-xs text-slate-600">
                        Example
                        <input className="h-8 rounded-md border border-slate-300 px-2 text-xs" value={edit.example} onChange={(event) => patchField(field.id, { example: event.target.value })} placeholder={`Example: ${stringifyValue(field.default)}`} />
                      </label>
                      <label className="flex items-center gap-2 text-xs text-slate-600">
                        <input type="checkbox" checked={edit.readonly ?? false} onChange={(event) => patchField(field.id, { readonly: event.target.checked })} />
                        Readonly (shown as text to researchers)
                      </label>
                      {(edit.io_role ?? "none") === "none" ? (
                        <div className="grid gap-2 rounded-md bg-slate-50 p-2">
                          <label className="grid gap-1 text-xs text-slate-600">
                            Structured type
                            <select
                              className="h-8 rounded-md border border-slate-300 px-2 text-xs"
                              value={edit.schema_ref ?? ""}
                              onChange={(event) => {
                                const ref = event.target.value;
                                if (!ref) patchField(field.id, { type: field.type, schema_ref: "", container: "single", type_schema: null });
                                else patchField(field.id, { type: "typed", schema_ref: ref, container: edit.container ?? "single" });
                              }}
                            >
                              <option value="">Plain value ({field.type})</option>
                              {libraryTypes.map((libType) => (
                                <option key={libType.name} value={libType.name}>{libType.name}</option>
                              ))}
                            </select>
                          </label>
                          {edit.schema_ref ? (
                            <label className="grid gap-1 text-xs text-slate-600">
                              Shape
                              <select
                                className="h-8 rounded-md border border-slate-300 px-2 text-xs"
                                value={edit.container ?? "single"}
                                onChange={(event) => patchField(field.id, { container: event.target.value as "single" | "list" | "map" })}
                              >
                                <option value="single">One {edit.schema_ref}</option>
                                <option value="list">List of {edit.schema_ref}</option>
                                <option value="map">Map (named entries) of {edit.schema_ref}</option>
                              </select>
                            </label>
                          ) : null}
                          {!edit.schema_ref && field.schema_suggestion ? (
                            <button
                              type="button"
                              className="w-fit rounded-md border border-cyan-300 px-2 py-1 text-xs font-semibold text-cyan-800"
                              onClick={() => patchField(field.id, { type: "typed", schema_ref: field.schema_suggestion ?? "", container: field.schema_suggestion_container ?? "single" })}
                            >
                              Looks like {field.schema_suggestion} ({field.schema_suggestion_container}) — apply
                            </button>
                          ) : null}
                          {libraryTypes.length === 0 ? (
                            <span className="text-[11px] text-slate-400">No library types yet — define them on the Environment page.</span>
                          ) : null}
                        </div>
                      ) : null}
                      <label className="grid gap-1 text-xs text-slate-600">
                        Researcher handling
                        <select
                          className="h-8 rounded-md border border-slate-300 px-2 text-xs"
                          value={edit.io_role ?? "none"}
                          onChange={(event) => {
                            const io_role = event.target.value as PublishedFieldIoRole;
                            // Switching to a file I/O role clears any structured-type binding (a typed
                            // value is a plain value, not a file), keeping the two mutually exclusive.
                            patchField(field.id, io_role === "none"
                              ? { io_role }
                              : { io_role, type: field.type, schema_ref: "", container: "single", type_schema: null });
                          }}
                        >
                          <option value="none">Server-managed (plain value)</option>
                          <option value="input">Input — researcher provides a file/folder</option>
                          <option value="output">Output — returned to the researcher</option>
                        </select>
                      </label>
                      {edit.io_role && edit.io_role !== "none" ? (
                        <div className="grid gap-2 rounded-md bg-slate-50 p-2">
                          <label className="grid gap-1 text-xs text-slate-600">
                            Accepts
                            <select
                              className="h-8 rounded-md border border-slate-300 px-2 text-xs"
                              value={edit.accept ?? "file"}
                              onChange={(event) => patchField(field.id, { accept: event.target.value as "file" | "directory" })}
                            >
                              <option value="file">A single file</option>
                              <option value="directory">A folder</option>
                            </select>
                          </label>
                          {edit.io_role === "input" ? (
                            <div className="flex flex-wrap gap-3 text-xs text-slate-600">
                              {(["upload", "shared"] as const).map((channel) => (
                                <label key={channel} className="flex items-center gap-1.5">
                                  <input
                                    type="checkbox"
                                    checked={(edit.sources ?? []).includes(channel)}
                                    onChange={(event) => patchField(field.id, { sources: toggleChannel(edit.sources, channel, event.target.checked) })}
                                  />
                                  {channel === "upload" ? "Upload from computer" : "Choose from shared storage"}
                                </label>
                              ))}
                            </div>
                          ) : (
                            <div className="flex flex-wrap gap-3 text-xs text-slate-600">
                              {(["download", "shared"] as const).map((channel) => (
                                <label key={channel} className="flex items-center gap-1.5">
                                  <input
                                    type="checkbox"
                                    checked={(edit.delivery ?? []).includes(channel)}
                                    onChange={(event) => patchField(field.id, { delivery: toggleChannel(edit.delivery, channel, event.target.checked) })}
                                  />
                                  {channel === "download" ? "Download archive" : "Write to shared storage"}
                                </label>
                              ))}
                            </div>
                          )}
                          {(edit.io_role === "input" && (edit.sources ?? []).includes("shared")) ||
                          (edit.io_role === "output" && (edit.delivery ?? []).includes("shared")) ? (
                            <div className="grid gap-1">
                              <input
                                className="h-8 rounded-md border border-slate-300 px-2 text-xs"
                                placeholder="Allowed shared roots (comma-separated ids)"
                                value={(edit.shared_roots ?? []).join(", ")}
                                onChange={(event) => patchField(field.id, { shared_roots: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })}
                              />
                              <span className="text-[11px] text-slate-400">
                                {availableRoots.length
                                  ? `Configured roots: ${availableRoots.map((root) => root.id).join(", ")}`
                                  : "No shared roots configured (set backend.shared_roots in app_config.yaml)."}
                              </span>
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-500">{field.help}</p>
                  )}
                </div>
              );
            })}
          </div>
        </section>
        }
      />
      </div>

      <ResizableSplitPane
        defaultSplit={60}
        left={
        <section className="grid gap-2 rounded-md border border-slate-200 bg-white p-4 h-full">
          <h3 className="text-sm font-semibold text-slate-950">Existing Published Jobs</h3>
          <div className="grid gap-2">
            {published.map((job) => (
              <div key={job.id} className="grid gap-2 rounded-md border border-slate-200 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-slate-900">{job.name}</span>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${statusClasses(job.status)}`}>{job.status}</span>
                </div>
                {job.description ? (
                  <p className="text-xs text-slate-500 whitespace-pre-line">{job.description}</p>
                ) : null}
                <p className="text-xs text-slate-500">
                  {job.fields.length} fields · v{job.version} · {runCounts[job.id] ?? 0} runs
                </p>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold" onClick={() => loadExisting(job.id).catch((cause: Error) => setError(cause.message))}>
                    Edit
                  </button>
                  <button type="button" className="rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold" onClick={() => duplicateCurrent(job.id).catch((cause: Error) => setError(cause.message))}>
                    Duplicate
                  </button>
                  {job.status !== "published" ? (
                    <button type="button" className="rounded-md bg-emerald-700 px-2 py-1 text-xs font-semibold text-white" onClick={() => publishPublishedJob(job.id).then(() => refresh()).catch((cause: Error) => setError(cause.message))}>
                      Publish
                    </button>
                  ) : null}
                  <button type="button" className="rounded-md border border-rose-200 px-2 py-1 text-xs font-semibold text-rose-700" onClick={() => deleteCurrent(job.id).catch((cause: Error) => setError(cause.message))}>
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
        }
        right={
        <section className="grid content-start gap-2 rounded-md border border-slate-200 bg-white p-4 h-full">
          <h3 className="text-sm font-semibold text-slate-950">Usage Status</h3>
          {(selectedRuns.length ? selectedRuns : allRuns).slice(0, 12).map((run) => (
            <div key={run.id} className="rounded-md border border-slate-200 p-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-slate-900">{run.published_job_name}</span>
                <span className={`rounded-full px-2 py-0.5 font-semibold ${statusClasses(run.status)}`}>{run.status}</span>
              </div>
              <p className="mt-1 text-slate-500">
                User: {run.user_display_name || run.username || run.user_id} · {run.total} tasks
              </p>
            </div>
          ))}
          {allRuns.length === 0 ? <p className="text-sm text-slate-500">No published job runs yet.</p> : null}
        </section>
        }
      />
    </section>
  );
}

// Small order-control button sized to match the drag handle. `variant` chooses a
// single/double chevron pointing up or down for move-up/down/to-top/to-bottom.
const REORDER_PATHS: Record<"top" | "up" | "down" | "bottom", string> = {
  top: "M2 6 L6 3 L10 6 M2 9.5 L6 6.5 L10 9.5",
  up: "M2 8 L6 4.5 L10 8",
  down: "M2 4 L6 7.5 L10 4",
  bottom: "M2 6 L6 9 L10 6 M2 2.5 L6 5.5 L10 2.5",
};

function ReorderButton({
  title,
  variant,
  disabled,
  onClick,
}: {
  title: string;
  variant: "top" | "up" | "down" | "bottom";
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      disabled={disabled}
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      className="rounded p-0.5 text-slate-400 hover:text-slate-700 disabled:cursor-default disabled:opacity-25 disabled:hover:text-slate-400"
    >
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
        <path d={REORDER_PATHS[variant]} />
      </svg>
    </button>
  );
}
