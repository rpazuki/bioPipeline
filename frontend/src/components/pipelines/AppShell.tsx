"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { PipelineProvider, usePipeline } from "./PipelineContext";

const NAV = [
  { href: "/", label: "Job Execution" },
  { href: "/job-definitions", label: "Job Definitions" },
  { href: "/validation", label: "Validation" },
  { href: "/storage", label: "Storage" },
];

function Header() {
  const { status } = usePipeline();
  const pathname = usePathname();

  return (
    <header className="border-b border-slate-200 bg-white px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-950">Bio Pipeline Manager</h1>
          <p className="mt-1 text-sm text-slate-500">Design, validate, queue, and run labUtils YAML pipelines.</p>
        </div>
        <div className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">{status}</div>
      </div>
      <nav className="mt-3 flex flex-wrap gap-2">
        {NAV.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`rounded-md px-3 py-1.5 text-sm font-semibold ${
                active ? "bg-cyan-700 text-white" : "border border-slate-300 text-slate-700"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
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
