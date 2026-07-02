"use client";

import { useState } from "react";

import type { SavedTypedValue } from "@/types";

// Manage the named cases of one multi-instance saved type (a `(type_key, container)`
// group): switch the active case, add a new one, rename it, mark it default, or delete
// it. Presentational — the parent owns persistence (API calls) and decides what value a
// new/updated case carries. Shared by the run form and the Saved Values page so inline
// case management behaves identically on both.
export default function SavedCasesControl({
  cases,
  selectedId,
  onSelect,
  onAdd,
  onRename,
  onSetDefault,
  onDelete,
  disabled,
}: {
  cases: SavedTypedValue[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onAdd: (name: string) => void;
  onRename: (id: string, name: string) => void;
  onSetDefault: (id: string) => void;
  onDelete: (id: string) => void;
  disabled?: boolean;
}) {
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const selected = cases.find((item) => item.id === selectedId) ?? null;

  function submitAdd() {
    const name = newName.trim();
    if (!name) return;
    onAdd(name);
    setNewName("");
    setAdding(false);
  }

  return (
    <div className="grid gap-1.5 rounded-md border border-violet-200 bg-violet-50/40 p-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-violet-700">Saved cases</span>
        {cases.length > 0 ? (
          <select
            aria-label="Saved case"
            className="h-8 rounded-md border border-slate-300 px-2 text-xs text-slate-950"
            value={selectedId ?? ""}
            disabled={disabled}
            onChange={(event) => onSelect(event.target.value)}
          >
            {cases.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name || "(unnamed)"}
                {item.is_default ? " · default" : ""}
              </option>
            ))}
          </select>
        ) : (
          <span className="text-[11px] text-slate-500">No cases yet — add one to save this value.</span>
        )}
        {selected ? (
          <>
            <button
              type="button"
              disabled={disabled || selected.is_default}
              onClick={() => onSetDefault(selected.id)}
              className="rounded-md border border-slate-300 px-2 py-1 text-[11px] font-semibold text-slate-600 disabled:opacity-40"
            >
              {selected.is_default ? "Default" : "Set default"}
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onDelete(selected.id)}
              className="rounded-md border border-rose-200 px-2 py-1 text-[11px] font-semibold text-rose-700 disabled:opacity-40"
            >
              Delete
            </button>
          </>
        ) : null}
        {adding ? null : (
          <button
            type="button"
            disabled={disabled}
            onClick={() => setAdding(true)}
            className="rounded-md border border-violet-300 px-2 py-1 text-[11px] font-semibold text-violet-700 disabled:opacity-40"
          >
            + Add case
          </button>
        )}
      </div>

      {adding ? (
        <div className="flex flex-wrap items-center gap-2">
          <input
            autoFocus
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                submitAdd();
              }
            }}
            placeholder="case name (e.g. SLAB)"
            className="h-8 w-40 rounded-md border border-slate-300 px-2 text-xs text-slate-950"
          />
          <button
            type="button"
            onClick={submitAdd}
            disabled={disabled || !newName.trim()}
            className="rounded-md bg-violet-700 px-2 py-1 text-[11px] font-semibold text-white disabled:opacity-40"
          >
            Add
          </button>
          <button
            type="button"
            onClick={() => {
              setAdding(false);
              setNewName("");
            }}
            className="rounded-md border border-slate-300 px-2 py-1 text-[11px] font-semibold text-slate-500"
          >
            Cancel
          </button>
        </div>
      ) : null}

      {selected ? (
        // Keyed by the selected case so the draft resets when the researcher switches.
        <RenameBox key={selected.id} initial={selected.name} disabled={disabled} onRename={(name) => onRename(selected.id, name)} />
      ) : null}
    </div>
  );
}

function RenameBox({ initial, onRename, disabled }: { initial: string; onRename: (name: string) => void; disabled?: boolean }) {
  const [name, setName] = useState(initial);
  const trimmed = name.trim();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-[11px] text-slate-500">Name</span>
      <input
        aria-label="Case name"
        value={name}
        onChange={(event) => setName(event.target.value)}
        disabled={disabled}
        className="h-8 w-40 rounded-md border border-slate-300 px-2 text-xs text-slate-950"
      />
      <button
        type="button"
        disabled={disabled || !trimmed || trimmed === initial}
        onClick={() => onRename(trimmed)}
        className="rounded-md border border-slate-300 px-2 py-1 text-[11px] font-semibold text-slate-600 disabled:opacity-40"
      >
        Rename
      </button>
    </div>
  );
}
