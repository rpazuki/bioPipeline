"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import AppShell from "./AppShell";
import { AuthProvider, useAuth } from "./AuthContext";

function LoginScreen() {
  const { error, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    try {
      await login(username, password);
    } catch {
      // AuthContext owns the user-facing error state.
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="grid min-h-screen place-items-center bg-slate-50 px-4">
      <form onSubmit={onSubmit} className="grid w-full max-w-sm gap-4 rounded-md border border-slate-200 bg-white p-5 shadow-sm">
        <div>
          <h1 className="text-lg font-semibold text-slate-950">Bio Pipeline Manager</h1>
          <p className="mt-1 text-sm text-slate-500">Sign in to continue.</p>
        </div>
        <label className="grid gap-1 text-sm font-semibold text-slate-700">
          Username
          <input
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-normal text-slate-950"
          />
        </label>
        <label className="grid gap-1 text-sm font-semibold text-slate-700">
          Password
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-normal text-slate-950"
          />
        </label>
        {error ? <p className="text-sm text-rose-700">{error}</p> : null}
        <button
          type="submit"
          disabled={busy || !username || !password}
          className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </main>
  );
}

function UnderConstructionScreen() {
  const { logout, user } = useAuth();
  return (
    <main className="grid min-h-screen place-items-center bg-slate-50 px-4">
      <section className="grid max-w-lg gap-4 rounded-md border border-slate-200 bg-white p-6 shadow-sm">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">Signed in as {user?.username}</p>
          <h1 className="mt-2 text-xl font-semibold text-slate-950">Your workspace is under construction</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            Standard user workflows are coming later. For now, your account can sign in successfully,
            but admin pipeline tools are not available for this role.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void logout()}
          className="w-fit rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
        >
          Sign out
        </button>
      </section>
    </main>
  );
}

function LoadingScreen() {
  return (
    <main className="grid min-h-screen place-items-center bg-slate-50 px-4 text-sm text-slate-500">
      Loading...
    </main>
  );
}

function AuthGateInner({ children }: { children: React.ReactNode }) {
  const { status, user } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (status === "unauthenticated" && pathname !== "/login") {
      router.replace("/login");
    }
    if (status === "authenticated" && user?.role === "user" && pathname !== "/under-construction") {
      router.replace("/under-construction");
    }
    if (status === "authenticated" && user?.role === "admin" && (pathname === "/login" || pathname === "/under-construction")) {
      router.replace("/");
    }
  }, [pathname, router, status, user?.role]);

  if (status === "loading") {
    return <LoadingScreen />;
  }
  if (status === "unauthenticated") {
    return <LoginScreen />;
  }
  if (user?.role === "user") {
    return <UnderConstructionScreen />;
  }
  return <AppShell>{children}</AppShell>;
}

export default function AuthGate({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AuthGateInner>{children}</AuthGateInner>
    </AuthProvider>
  );
}
