"use client";

import { useEffect, useMemo, useState } from "react";

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
  publishPublishedJob,
  updatePublishedJob,
  validatePublishedJob,
} from "@/lib/api";
import ResizableSplitPane from "@/components/pipelines/ResizableSplitPane";
import type { DefinitionSummary, PublishedField, PublishedFieldIoRole, PublishedJobAdmin, PublishedRunSummary, SharedRootInfo } from "@/types";

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

function mergeFields(candidates: PublishedField[], existing: PublishedField[]) {
  const byId = new Map(candidates.map((field) => [field.id, field]));
  const idByBinding = new Map(candidates.map((field) => [JSON.stringify(field.bindings ?? []), field.id]));
  for (const field of existing) {
    const targetId = idByBinding.get(JSON.stringify(field.bindings ?? [])) ?? field.id;
    byId.set(targetId, { ...byId.get(targetId), ...field, id: targetId });
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
  const [selectedRuns, setSelectedRuns] = useState<PublishedRunSummary[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [definitionContent, setDefinitionContent] = useState("");
  const [definitionName, setDefinitionName] = useState("");
  const [candidates, setCandidates] = useState<PublishedField[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [fieldEdits, setFieldEdits] = useState<Record<string, PublishedField>>({});
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("Ready");

  const selectedFields = useMemo(
    () => candidates.filter((field) => selectedIds.has(field.id)).map((field) => fieldEdits[field.id] ?? field),
    [candidates, fieldEdits, selectedIds],
  );
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

  async function refresh() {
    const [defs, jobs, runs, roots] = await Promise.all([
      listSavedDefinitions(),
      listAdminPublishedJobs(),
      listAdminPublishedRuns(),
      listAdminSharedRoots().catch(() => [] as SharedRootInfo[]),
    ]);
    setDefinitions(defs);
    setPublished(jobs);
    setAllRuns(runs);
    setAvailableRoots(roots);
  }

  useEffect(() => {
    refresh().catch((cause: Error) => setError(cause.message));
  }, []);

  function clearEditor() {
    setEditingId(null);
    setName("");
    setDescription("");
    setDefinitionName("");
    setDefinitionContent("");
    setCandidates([]);
    setSelectedIds(new Set());
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
    setSelectedIds(new Set(selectedFields.map((field) => field.id).filter((id) => mergedIds.has(id))));
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
    setSelectedIds(selectedFieldIds(job.fields, merged));
    setFieldEdits(Object.fromEntries(merged.map((field) => [field.id, field])));
    setSelectedRuns(runs);
    setStatus(`Editing ${job.name} · ${job.status} · v${job.version}`);
  }

  function toggleField(field: PublishedField) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(field.id)) next.delete(field.id);
      else next.add(field.id);
      return next;
    });
    setFieldEdits((current) => ({ ...current, [field.id]: current[field.id] ?? field }));
  }

  function patchField(fieldId: string, patch: Partial<PublishedField>) {
    setFieldEdits((current) => ({ ...current, [fieldId]: { ...current[fieldId], ...patch } }));
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
        <span className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">{status}</span>
      </div>

      {error ? <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}

      <ResizableSplitPane
        defaultSplit={55}
        left={
        <section className="grid gap-3 rounded-md border border-slate-200 bg-white p-4 h-full">
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
        <section className="grid content-start gap-3 rounded-md border border-slate-200 bg-white p-4 h-full">
          <h3 className="text-sm font-semibold text-slate-950">Definable Fields</h3>
          {candidates.length === 0 ? <p className="text-sm text-slate-500">Load or inspect a Job Definition to choose public fields.</p> : null}
          <div className="grid max-h-[760px] gap-2 overflow-auto pr-1">
            {candidates.map((field) => {
              const edit = fieldEdits[field.id] ?? field;
              const selected = selectedIds.has(field.id);
              return (
                <div key={field.id} className="grid gap-2 rounded-md border border-slate-200 p-3">
                  <label className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                    <input type="checkbox" checked={selected} onChange={() => toggleField(field)} />
                    {field.label}
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">{field.type}</span>
                  </label>
                  {selected ? (
                    <div className="grid gap-2">
                      <input className="h-8 rounded-md border border-slate-300 px-2 text-xs" value={edit.label} onChange={(event) => patchField(field.id, { label: event.target.value })} />
                      <input className="h-8 rounded-md border border-slate-300 px-2 text-xs" value={edit.help} onChange={(event) => patchField(field.id, { help: event.target.value })} />
                      <input className="h-8 rounded-md border border-slate-300 px-2 text-xs" value={edit.example} onChange={(event) => patchField(field.id, { example: event.target.value })} placeholder={`Example: ${stringifyValue(field.default)}`} />
                      <label className="flex items-center gap-2 text-xs text-slate-600">
                        <input type="checkbox" checked={edit.readonly ?? false} onChange={(event) => patchField(field.id, { readonly: event.target.checked })} />
                        Readonly (shown as text to researchers)
                      </label>
                      <label className="grid gap-1 text-xs text-slate-600">
                        Researcher handling
                        <select
                          className="h-8 rounded-md border border-slate-300 px-2 text-xs"
                          value={edit.io_role ?? "none"}
                          onChange={(event) => patchField(field.id, { io_role: event.target.value as PublishedFieldIoRole })}
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
