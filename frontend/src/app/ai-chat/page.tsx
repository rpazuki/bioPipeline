"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { executeAITool, getAIContext, sendAIChatMessage, testAIProvider } from "@/lib/api";
import ResizableSplitPane from "@/components/pipelines/ResizableSplitPane";
import type {
  AIChatMessage,
  AIContextResponse,
  AIProviderStatus,
  AIToolCallRecord,
} from "@/types";

type DeepLink = { href: string; label: string };

// Saved artifacts map to the admin page that manages them.
const ARTIFACT_LINKS: Record<string, { href: string; label: (result: Record<string, unknown>) => string }> = {
  save_pipeline_yaml: { href: "/storage", label: (r) => `Pipeline Storage: ${r.name ?? ""}` },
  save_job_definition: { href: "/job-storage", label: (r) => `Job Storage: ${r.name ?? ""}` },
};

// Tailwind-styled renderers so GitHub-flavored Markdown (tables, lists, code)
// reads well in the assistant bubble.
const MARKDOWN_COMPONENTS: Components = {
  p: ({ children }) => <p className="my-1.5 leading-relaxed first:mt-0 last:mb-0">{children}</p>,
  h1: ({ children }) => <h1 className="mb-1.5 mt-2 text-base font-semibold">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-1.5 mt-2 text-sm font-semibold">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1 mt-2 text-sm font-semibold">{children}</h3>,
  ul: ({ children }) => <ul className="my-1.5 list-disc pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-1.5 list-decimal pl-5">{children}</ol>,
  li: ({ children }) => <li className="my-0.5">{children}</li>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-cyan-700 underline">
      {children}
    </a>
  ),
  code: ({ className, children }) =>
    className?.includes("language-") ? (
      <code className={className}>{children}</code>
    ) : (
      <code className="rounded bg-slate-200/70 px-1 py-0.5 font-mono text-[0.8em]">{children}</code>
    ),
  pre: ({ children }) => (
    <pre className="my-2 overflow-auto rounded-md bg-slate-900 p-3 font-mono text-xs text-slate-100">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="my-2 overflow-auto">
      <table className="w-full border-collapse text-xs">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-slate-100">{children}</thead>,
  th: ({ children }) => (
    <th className="border border-slate-300 px-2 py-1 text-left font-semibold">{children}</th>
  ),
  td: ({ children }) => <td className="border border-slate-200 px-2 py-1 align-top">{children}</td>,
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-slate-300 pl-3 text-slate-600">{children}</blockquote>
  ),
};

type Drafts = {
  pipeline_yaml: string;
  job_definition: string;
};

const EMPTY_DRAFTS: Drafts = { pipeline_yaml: "", job_definition: "" };

function asText(content: unknown): string {
  if (typeof content === "string") return content;
  return JSON.stringify(content, null, 2);
}

// Copy text to the clipboard, falling back to a hidden textarea + execCommand
// when the async Clipboard API is unavailable (e.g. a non-HTTPS dev host).
async function copyText(text: string): Promise<boolean> {
  if (!text) return false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through to the legacy path below.
  }
  try {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(textarea);
    return ok;
  } catch {
    return false;
  }
}

// Persist the conversation so it survives navigating away from the page and
// full reloads. Cleared by the Reset button.
const STORAGE_KEY = "ai-designer-conversation-v1";

type PersistedState = {
  provider: string;
  messages: AIChatMessage[];
  input: string;
  toolCalls: AIToolCallRecord[];
  drafts: Drafts;
  pendingConfirmation: AIToolCallRecord | null;
  confirmations: Record<string, boolean>;
};

function loadPersisted(): Partial<PersistedState> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") as Partial<PersistedState>;
  } catch {
    return {};
  }
}

export default function AIChatPage() {
  const persisted = useMemo(loadPersisted, []);
  const [context, setContext] = useState<AIContextResponse | null>(null);
  const [provider, setProvider] = useState<string>(persisted.provider ?? "");
  const [messages, setMessages] = useState<AIChatMessage[]>(persisted.messages ?? []);
  const [input, setInput] = useState(persisted.input ?? "");
  const [toolCalls, setToolCalls] = useState<AIToolCallRecord[]>(persisted.toolCalls ?? []);
  const [drafts, setDrafts] = useState<Drafts>(persisted.drafts ?? EMPTY_DRAFTS);
  const [pendingConfirmation, setPendingConfirmation] = useState<AIToolCallRecord | null>(
    persisted.pendingConfirmation ?? null,
  );
  const [confirmations, setConfirmations] = useState<Record<string, boolean>>(
    persisted.confirmations ?? {},
  );
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Loading provider configuration...");
  const [error, setError] = useState<string | null>(null);

  const selectedStatus: AIProviderStatus | undefined = useMemo(
    () => context?.providers.find((item) => item.provider === provider),
    [context, provider],
  );

  const deepLinks: DeepLink[] = useMemo(() => {
    const seen = new Set<string>();
    const links: DeepLink[] = [];
    for (const call of toolCalls) {
      if (call.status !== "succeeded" || !call.result) continue;
      const spec = ARTIFACT_LINKS[call.name];
      if (!spec) continue;
      const label = spec.label(call.result);
      const key = `${spec.href}:${label}`;
      if (seen.has(key)) continue;
      seen.add(key);
      links.push({ href: spec.href, label });
    }
    return links;
  }, [toolCalls]);

  const validation = useMemo(() => {
    let pipeline: boolean | null = null;
    let taskCount: number | null = null;
    for (const call of toolCalls) {
      if (call.status !== "succeeded" || !call.result) continue;
      if (call.name === "validate_pipeline_yaml") pipeline = Boolean(call.result.is_valid);
      if (call.name === "preview_job_definition" && typeof call.result.task_count === "number") {
        taskCount = call.result.task_count;
      }
    }
    return { pipeline, taskCount };
  }, [toolCalls]);

  useEffect(() => {
    getAIContext()
      .then((data) => {
        setContext(data);
        // Keep a restored provider selection; only default when none persisted.
        setProvider((current) => current || data.default_provider);
        setStatus(`Schema context ${data.schema_digest} · ${data.tools.length} tools available`);
      })
      .catch((cause: Error) => {
        setError(cause.message);
        setStatus("Provider configuration unavailable");
      });
  }, []);

  // Persist conversation state across navigation/reload.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const payload: PersistedState = {
      provider,
      messages,
      input,
      toolCalls,
      drafts,
      pendingConfirmation,
      confirmations,
    };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }, [provider, messages, input, toolCalls, drafts, pendingConfirmation, confirmations]);

  function resetConversation() {
    setMessages([]);
    setInput("");
    setToolCalls([]);
    setDrafts(EMPTY_DRAFTS);
    setPendingConfirmation(null);
    setConfirmations({});
    setError(null);
    setStatus("Conversation reset");
    if (typeof window !== "undefined") window.localStorage.removeItem(STORAGE_KEY);
  }

  function applyDrafts(updates: { kind: keyof Drafts; content: unknown }[]) {
    if (updates.length === 0) return;
    setDrafts((current) => {
      const next = { ...current };
      for (const draft of updates) next[draft.kind] = asText(draft.content);
      return next;
    });
  }

  async function send(extraConfirmations: Record<string, boolean> = {}) {
    const trimmed = input.trim();
    if (!trimmed || busy) return;
    setError(null);
    setBusy(true);
    const userMessage: AIChatMessage = { role: "user", content: trimmed };
    const history = [...messages, userMessage];
    setMessages(history);
    setInput("");
    const mergedConfirmations = { ...confirmations, ...extraConfirmations };
    try {
      const response = await sendAIChatMessage({
        provider: { provider: provider as never },
        messages: history,
        confirmations: mergedConfirmations,
        active_pipeline_yaml: drafts.pipeline_yaml,
        active_job_definition: drafts.job_definition,
      });
      setMessages((current) => [...current, response.message]);
      if (response.tool_calls.length) setToolCalls((current) => [...current, ...response.tool_calls]);
      applyDrafts(response.drafts.map((draft) => ({ kind: draft.kind, content: draft.content })));
      setPendingConfirmation(response.needs_confirmation ?? null);
      setStatus(
        response.needs_confirmation
          ? `Awaiting confirmation for ${response.needs_confirmation.name}`
          : `Ran ${response.tool_calls.length} tool${response.tool_calls.length === 1 ? "" : "s"}`,
      );
    } catch (cause) {
      setError((cause as Error).message);
      setStatus("Message failed");
    } finally {
      setBusy(false);
    }
  }

  async function confirmPending() {
    if (!pendingConfirmation || busy) return;
    setError(null);
    setBusy(true);
    try {
      const record = await executeAITool(
        pendingConfirmation.name,
        pendingConfirmation.arguments,
        true,
      );
      setToolCalls((current) => [...current, record]);
      setConfirmations((current) => ({ ...current, [pendingConfirmation.name]: true }));
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content:
            record.status === "succeeded"
              ? `Confirmed and executed ${record.name}.`
              : `Confirmed ${record.name} but it failed: ${record.error ?? "unknown error"}`,
        },
      ]);
      setPendingConfirmation(null);
      setStatus(`Confirmed ${record.name} · ${record.status}`);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function runProviderTest() {
    setError(null);
    try {
      const result = await testAIProvider({ provider: provider as never });
      setStatus(`${result.provider} ready · model ${result.model || "(default)"}`);
    } catch (cause) {
      setError((cause as Error).message);
      setStatus("Provider test failed");
    }
  }

  return (
    <section className="grid gap-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">AI Designer</h2>
          <p className="mt-1 text-sm text-slate-500">
            Describe a workflow in natural language. The agent inspects storage, drafts Pipeline and
            Job Definition YAML, validates and previews it, and saves the result. Publishing a
            user-facing job is done manually on the Job Publishing page.
          </p>
        </div>
        <span className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
          {status}
        </span>
      </div>

      {error ? <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}

      {/* Provider controls */}
      <section className="grid gap-3 rounded-md border border-slate-200 bg-white p-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1 text-xs font-semibold text-slate-600">
            Provider
            <select
              className="h-9 rounded-md border border-slate-300 px-3 text-sm"
              value={provider}
              onChange={(event) => setProvider(event.target.value)}
            >
              {(context?.providers ?? []).map((item) => (
                <option key={item.provider} value={item.provider} disabled={!item.enabled}>
                  {item.provider}
                  {item.is_default ? " (default)" : ""}
                  {item.enabled ? "" : " — disabled"}
                </option>
              ))}
            </select>
          </label>
          <div className="grid gap-1 text-xs font-semibold text-slate-600">
            Status
            <div className="flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 text-xs font-normal text-slate-600">
              <span
                className={`rounded-full px-2 py-0.5 font-semibold ${
                  selectedStatus?.configured ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"
                }`}
              >
                {selectedStatus?.configured ? "configured" : "not configured"}
              </span>
              <span>model: {selectedStatus?.model || "(backend default)"}</span>
            </div>
          </div>
        </div>
        <button
          type="button"
          className="h-9 rounded-md border border-slate-300 px-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          onClick={() => void runProviderTest()}
          disabled={!provider}
        >
          Test provider
        </button>
      </section>

      {/* Chat thread */}
      <section className="grid content-start gap-3 rounded-md border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-slate-950">Conversation</h3>
            <button
              type="button"
              className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
              onClick={() => {
                if (messages.length && !window.confirm("Reset the conversation and clear drafts?")) return;
                resetConversation();
              }}
              disabled={busy || (messages.length === 0 && !drafts.pipeline_yaml && !drafts.job_definition)}
            >
              Reset
            </button>
          </div>
          <div className="grid max-h-[520px] gap-2 overflow-auto pr-1">
            {messages.length === 0 ? (
              <p className="text-sm text-slate-500">
                Ask the agent to design a pipeline or job definition from an existing YAML.
              </p>
            ) : null}
            {messages.map((message, index) => (
              <div
                key={index}
                className={`rounded-md border p-3 text-sm ${
                  message.role === "user"
                    ? "border-slate-200 bg-slate-50 text-slate-800"
                    : "border-cyan-200 bg-cyan-50/60 text-slate-900"
                }`}
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                    {message.role}
                  </span>
                  {message.role === "assistant" && message.content ? (
                    <CopyButton text={message.content} title="Copy as Markdown" />
                  ) : null}
                </div>
                {message.role === "assistant" ? (
                  <div className="text-sm text-slate-900">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
                      {message.content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <div className="whitespace-pre-wrap">{message.content}</div>
                )}
              </div>
            ))}
          </div>

          {pendingConfirmation ? (
            <div className="grid gap-2 rounded-md border border-amber-300 bg-amber-50 p-3">
              <p className="text-sm font-semibold text-amber-900">
                Confirmation required: {pendingConfirmation.name}
              </p>
              <pre className="max-h-32 overflow-auto rounded-md bg-white p-2 text-xs text-slate-700">
                {JSON.stringify(pendingConfirmation.arguments, null, 2)}
              </pre>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="rounded-md bg-amber-600 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
                  onClick={() => void confirmPending()}
                  disabled={busy}
                >
                  Confirm &amp; run
                </button>
                <button
                  type="button"
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700"
                  onClick={() => setPendingConfirmation(null)}
                >
                  Dismiss
                </button>
              </div>
            </div>
          ) : null}

          <div className="grid gap-2">
            <textarea
              className="min-h-24 rounded-md border border-slate-300 p-3 text-sm"
              placeholder="Describe the workflow you want to design..."
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                  event.preventDefault();
                  void send();
                }
              }}
              spellCheck={false}
            />
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-slate-400">⌘/Ctrl + Enter to send</span>
              <button
                type="button"
                className="rounded-md bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                onClick={() => void send()}
                disabled={busy || !input.trim()}
              >
                {busy ? "Working..." : "Send"}
              </button>
            </div>
          </div>
      </section>

      {/* Results strip: validation badges + deep links to artifact pages */}
      {validation.pipeline !== null || validation.taskCount !== null || deepLinks.length ? (
        <section className="flex flex-wrap items-center gap-2 rounded-md border border-slate-200 bg-white p-3">
          {validation.pipeline !== null ? (
            <span
              className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                validation.pipeline ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"
              }`}
            >
              Pipeline YAML {validation.pipeline ? "valid" : "invalid"}
            </span>
          ) : null}
          {validation.taskCount !== null ? (
            <span className="rounded-full bg-cyan-100 px-2.5 py-1 text-xs font-semibold text-cyan-800">
              Preview: {validation.taskCount} task{validation.taskCount === 1 ? "" : "s"}
            </span>
          ) : null}
          {deepLinks.map((link) => (
            <Link
              key={link.href + link.label}
              href={link.href}
              className="rounded-full border border-slate-300 px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50"
            >
              {link.label} →
            </Link>
          ))}
        </section>
      ) : null}

      {/* Draft workspace */}
      <ResizableSplitPane
        defaultSplit={50}
        left={
          <DraftPanel
            title="Pipeline YAML"
            filename="pipeline.yaml"
            value={drafts.pipeline_yaml}
            onChange={(value) => setDrafts((current) => ({ ...current, pipeline_yaml: value }))}
          />
        }
        right={
          <DraftPanel
            title="Job Definition"
            filename="job_definition.yaml"
            value={drafts.job_definition}
            onChange={(value) => setDrafts((current) => ({ ...current, job_definition: value }))}
          />
        }
      />
    </section>
  );
}

function CopyButton({ text, label = "Copy", title }: { text: string; label?: string; title?: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    if (await copyText(text)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  }

  return (
    <button
      type="button"
      className="rounded-md border border-slate-300 bg-white/70 px-2 py-0.5 text-[11px] font-semibold text-slate-600 hover:bg-white disabled:opacity-40"
      onClick={() => void handleCopy()}
      disabled={!text}
      title={title}
    >
      {copied ? "Copied" : label}
    </button>
  );
}

function DraftPanel({
  title,
  filename,
  value,
  onChange,
}: {
  title: string;
  filename: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    if (!value) return;
    if (await copyText(value)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  }

  function download() {
    if (!value) return;
    const blob = new Blob([value], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="grid content-start gap-2 rounded-md border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
        <div className="flex gap-1.5">
          <button
            type="button"
            className="rounded-md border border-slate-300 px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            onClick={() => void copy()}
            disabled={!value}
          >
            {copied ? "Copied" : "Copy"}
          </button>
          <button
            type="button"
            className="rounded-md border border-slate-300 px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            onClick={download}
            disabled={!value}
          >
            Download
          </button>
        </div>
      </div>
      <textarea
        className="min-h-64 rounded-md border border-slate-300 p-3 font-mono text-xs"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={`${title} drafted by the agent will appear here.`}
        spellCheck={false}
      />
    </section>
  );
}
