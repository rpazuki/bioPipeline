"use client";

import { useState } from "react";

import { changePassword } from "@/lib/api";
import { useAuth } from "@/components/pipelines/AuthContext";

const MIN_LENGTH = 8;

export default function ChangePasswordPage() {
  const { user } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  // Client-side guards mirror the server: a clear inline message beats a round
  // trip that returns the same complaint. The server stays the source of truth
  // (it alone can confirm the current password).
  const tooShort = next.length > 0 && next.length < MIN_LENGTH;
  const mismatch = confirm.length > 0 && next !== confirm;
  const unchanged = next.length > 0 && next === current;
  const canSubmit =
    !busy &&
    current.length > 0 &&
    next.length >= MIN_LENGTH &&
    next === confirm &&
    next !== current;

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      await changePassword(current, next);
      setDone(true);
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="p-5">
      <form
        onSubmit={onSubmit}
        className="grid w-full max-w-md gap-4 rounded-md border border-slate-200 bg-white p-5"
      >
        <div>
          <h2 className="text-lg font-semibold text-slate-950">Change Password</h2>
          <p className="mt-1 text-sm text-slate-500">
            Update the password for <span className="font-semibold text-slate-700">{user?.username}</span>. Enter your
            current password to confirm it&apos;s you.
          </p>
        </div>

        <label className="grid gap-1 text-sm font-semibold text-slate-700">
          Current password
          <input
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-normal text-slate-950"
          />
        </label>

        <label className="grid gap-1 text-sm font-semibold text-slate-700">
          New password
          <input
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(event) => setNext(event.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-normal text-slate-950"
          />
          <span className="text-xs font-normal text-slate-400">At least {MIN_LENGTH} characters.</span>
        </label>

        <label className="grid gap-1 text-sm font-semibold text-slate-700">
          Confirm new password
          <input
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-normal text-slate-950"
          />
        </label>

        {tooShort ? <p className="text-sm text-amber-700">New password must be at least {MIN_LENGTH} characters.</p> : null}
        {mismatch ? <p className="text-sm text-amber-700">New password and confirmation do not match.</p> : null}
        {unchanged ? <p className="text-sm text-amber-700">New password must differ from the current one.</p> : null}
        {error ? <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}
        {done ? <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">Password updated.</p> : null}

        <button
          type="submit"
          disabled={!canSubmit}
          className="w-fit rounded-md bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Updating…" : "Update password"}
        </button>
      </form>
    </section>
  );
}
