"use client";

import { useCallback, useEffect, useState } from "react";

import { createUser, disableUser, enableUser, listUsers, resetUserPassword, updateUser } from "@/lib/api";
import type { User, UserRole } from "@/types";

function roleLabel(role: UserRole) {
  return role === "admin" ? "Administrator" : "Researcher";
}

export default function UserManagementPanel() {
  const [users, setUsers] = useState<User[]>([]);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("user");
  const [resetPasswords, setResetPasswords] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const data = await listUsers();
    setUsers(data);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const run = useCallback(async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [refresh]);

  const onCreate = () =>
    run(async () => {
      await createUser({
        username,
        display_name: displayName,
        password,
        role,
        is_active: true,
      });
      setUsername("");
      setDisplayName("");
      setPassword("");
      setRole("user");
    });

  const onResetPassword = (user: User) =>
    run(async () => {
      const value = resetPasswords[user.id] ?? "";
      await resetUserPassword(user.id, value);
      setResetPasswords((current) => ({ ...current, [user.id]: "" }));
    });

  const onToggleActive = (user: User) =>
    run(async () => {
      if (user.is_active) {
        await disableUser(user.id);
      } else {
        await enableUser(user.id);
      }
    });

  const onRoleChange = (user: User, nextRole: UserRole) =>
    run(async () => {
      await updateUser(user.id, { role: nextRole });
    });

  return (
    <div className="grid gap-4">
      <section className="grid gap-3 rounded-md border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Create researcher</h2>
        <div className="grid gap-2 md:grid-cols-[1fr_1fr_1fr_auto_auto]">
          <input
            aria-label="New username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="username"
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            aria-label="Display name"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            placeholder="display name"
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            type="password"
            aria-label="Initial password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="initial password"
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <select
            aria-label="New user role"
            value={role}
            onChange={(event) => setRole(event.target.value as UserRole)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="user">Researcher</option>
            <option value="admin">Administrator</option>
          </select>
          <button
            type="button"
            onClick={onCreate}
            disabled={busy || !username || !password}
            className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            Create
          </button>
        </div>
        {error ? <p className="text-xs text-rose-700">{error}</p> : null}
      </section>

      <section className="overflow-hidden rounded-md border border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-900">Researchers ({users.length})</h2>
        </div>
        <div className="grid divide-y divide-slate-200">
          {users.map((user) => (
            <div key={user.id} className="grid gap-3 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-mono text-sm font-semibold text-slate-950">{user.username}</div>
                  <div className="text-xs text-slate-500">
                    {user.display_name || "No display name"} · {roleLabel(user.role)} · {user.is_active ? "active" : "disabled"}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onToggleActive(user)}
                  disabled={busy}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 disabled:opacity-50"
                >
                  {user.is_active ? "Disable" : "Enable"}
                </button>
              </div>
              <div className="grid gap-2 md:grid-cols-[1fr_auto_1fr_auto]">
                <input
                  aria-label={`Display name for ${user.username}`}
                  defaultValue={user.display_name}
                  onBlur={(event) => {
                    const value = event.target.value;
                    if (value !== user.display_name) {
                      void run(() => updateUser(user.id, { display_name: value }).then(() => undefined));
                    }
                  }}
                  className="rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
                <select
                  aria-label={`Role for ${user.username}`}
                  value={user.role}
                  onChange={(event) => onRoleChange(user, event.target.value as UserRole)}
                  disabled={busy}
                  className="rounded-md border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="user">Researcher</option>
                  <option value="admin">Administrator</option>
                </select>
                <input
                  type="password"
                  aria-label={`New password for ${user.username}`}
                  value={resetPasswords[user.id] ?? ""}
                  onChange={(event) => setResetPasswords((current) => ({ ...current, [user.id]: event.target.value }))}
                  placeholder="new password"
                  className="rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
                <button
                  type="button"
                  onClick={() => onResetPassword(user)}
                  disabled={busy || !(resetPasswords[user.id] ?? "")}
                  className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:opacity-50"
                >
                  Reset password
                </button>
              </div>
            </div>
          ))}
          {users.length === 0 ? <p className="p-4 text-sm text-slate-500">No researchers yet.</p> : null}
        </div>
      </section>
    </div>
  );
}
