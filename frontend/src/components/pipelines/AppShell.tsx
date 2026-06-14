"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { useAuth } from "./AuthContext";
import { PipelineProvider, usePipeline } from "./PipelineContext";

const NAV = [
  { href: "/ai-chat", label: "AI Designer" },
  { href: "/published-jobs-admin", label: "Job Publishing" },
  { href: "/", label: "Job Queue" },
  { href: "/job-definitions", label: "Job Definitions" },
  { href: "/job-storage", label: "Job Storage" },
  { href: "/submit", label: "Pipeline Submit" },
  { href: "/validation", label: "Pipeline Definitions" },
  { href: "/storage", label: "Pipeline Storage" },
  { href: "/environment", label: "Environment" },
  { href: "/users", label: "Researchers" },
  { href: "/change-password", label: "Change Password" },
];

const USER_NAV = [
  { href: "/published-jobs", label: "Published Jobs" },
  { href: "/saved-values", label: "Saved Values" },
  { href: "/my-runs", label: "My Runs" },
  { href: "/change-password", label: "Change Password" },
];

function roleLabel(role?: string) {
  if (role === "admin") return "Administrator";
  if (role === "user") return "Researcher";
  return role ?? "";
}

function Header() {
  const { status } = usePipeline();
  const { logout, user } = useAuth();
  const pathname = usePathname();
  const [open, setOpen] = useState(true);

  return (
    <header className="border-b border-slate-200 bg-white">
      {/* Top bar */}
      <div className="flex items-center justify-between gap-3 px-5 py-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-950">Bio Pipeline Manager</h1>
          <p className="text-xs text-slate-500">Design, validate, queue, and run labUtils YAML pipelines.</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <div className="text-right text-xs text-slate-500">
            <div className="font-semibold text-slate-700">{user?.username}</div>
            <div>{roleLabel(user?.role)}</div>
          </div>
          <button
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-1.5 rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            aria-expanded={open}
            aria-label="Toggle navigation"
          >
            <svg
              className={`h-4 w-4 transition-transform ${open ? "rotate-90" : ""}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
            Menu
          </button>
          <button
            type="button"
            onClick={() => void logout()}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            Sign out
          </button>
        </div>
      </div>

      {/* Collapsible nav */}
      {open && (
        <nav className="border-t border-slate-100 px-5 pb-3 pt-2 flex flex-wrap gap-2">
          {(user?.role === "admin" ? NAV : USER_NAV).map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-md px-3 py-1.5 text-sm font-semibold ${
                  active ? "bg-cyan-700 text-white" : "border border-slate-300 text-slate-700 hover:bg-slate-50"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      )}

      {/* Status bar — always visible, full width */}
      <div className="border-t border-slate-100 bg-slate-50 px-5 py-1.5 text-xs text-slate-600">
        <span className="font-semibold text-slate-400 uppercase tracking-wide mr-2">Last action:</span>
        {status}
      </div>
    </header>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <PipelineProvider>
      <main className="min-h-screen bg-slate-50">
        <Header />
        {children}
      </main>
    </PipelineProvider>
  );
}
