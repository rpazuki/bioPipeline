"use client";

import UserManagementPanel from "@/components/pipelines/UserManagementPanel";

export default function UsersPage() {
  return (
    <div className="grid gap-4 p-5">
      <section className="rounded-md border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Users</h2>
        <p className="mt-1 text-xs text-slate-500">
          Manage application accounts. Admins can use the current pipeline tools; standard users
          can sign in but land on the under-construction workspace for now.
        </p>
      </section>
      <UserManagementPanel />
    </div>
  );
}
