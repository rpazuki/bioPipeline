"use client";

import { useEffect, useMemo, useState } from "react";

import { executeAITool, getAIContext, sendAIChatMessage, testAIProvider } from "@/lib/api";
import type {
  AIChatMessage,
  AIContextResponse,
  AIProviderStatus,
  AIToolCallRecord,
} from "@/types";

type Drafts = {
  pipeline_yaml: string;
  job_definition: string;
  published_fields: string;
};

const EMPTY_DRAFTS: Drafts = { pipeline_yaml: "", job_definition: "", published_fields: "" };

function asText(content: unknown): string {
  if (typeof content === "string") return content;
  return JSON.stringify(content, null, 2);
}

function toolStatusClasses(status: string): string {
  switch (status) {
    case "succeeded":
      return "bg-emerald-100 text-emerald-800";
    case "failed":
      return "bg-rose-100 text-rose-800";
    case "pending_confirmation":
      return "bg-amber-100 text-amber-800";
    case "running":
      return "bg-cyan-100 text-cyan-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

export default function AIChatPage() {
  const [context, setContext] = useState<AIContextResponse | null>(null);
  const [provider, setProvider] = useState<string>("");
  const [messages, setMessages] = useState<AIChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [toolCalls, setToolCalls] = useState<AIToolCallRecord[]>([]);
  const [drafts, setDrafts] = useState<Drafts>(EMPTY_DRAFTS);
  const [pendingConfirmation, setPendingConfirmation] = useState<AIToolCallRecord | null>(null);
  const [confirmations, setConfirmations] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Loading provider configuration...");
  const [error, setError] = useState<string | null>(null);

  const selectedStatus: AIProviderStatus | undefined = useMemo(
    () => context?.providers.find((item) => item.provider === provider),
    [context, provider],
  );

  useEffect(() => {
    getAIContext()
      .then((data) => {
        setContext(data);
        setProvider(data.default_provider);
        setStatus(`Schema context ${data.schema_digest} · ${data.tools.length} tools available`);
      })
      .catch((cause: Error) => {
        setError(cause.message);
        setStatus("Provider configuration unavailable");
      });
  }, []);

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
            Job Definition YAML, validates and previews it, and prepares Published Jobs. Submit and
            publish require your explicit confirmation.
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

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(380px,0.8fr)]">
        {/* Chat thread */}
        <section className="grid content-start gap-3 rounded-md border border-slate-200 bg-white p-4">
          <h3 className="text-sm font-semibold text-slate-950">Conversation</h3>
          <div className="grid max-h-[460px] gap-2 overflow-auto pr-1">
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
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  {message.role}
                </div>
                <div className="whitespace-pre-wrap">{message.content}</div>
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

        {/* Tool trace */}
        <section className="grid content-start gap-2 rounded-md border border-slate-200 bg-white p-4">
          <h3 className="text-sm font-semibold text-slate-950">Tool Trace</h3>
          {toolCalls.length === 0 ? (
            <p className="text-sm text-slate-500">Tool calls the agent runs will appear here.</p>
          ) : null}
          <div className="grid max-h-[560px] gap-2 overflow-auto pr-1">
            {toolCalls.map((call) => (
              <div key={call.id} className="grid gap-1 rounded-md border border-slate-200 p-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-semibold text-slate-800">{call.name}</span>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${toolStatusClasses(call.status)}`}>
                    {call.status}
                  </span>
                </div>
                {call.error ? <p className="text-xs text-rose-700">{call.error}</p> : null}
                {call.result ? (
                  <pre className="max-h-32 overflow-auto rounded-md bg-slate-50 p-2 text-[11px] text-slate-600">
                    {JSON.stringify(call.result, null, 2)}
                  </pre>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* Draft workspace */}
      <div className="grid gap-4 lg:grid-cols-3">
        <DraftPanel
          title="Pipeline YAML"
          value={drafts.pipeline_yaml}
          onChange={(value) => setDrafts((current) => ({ ...current, pipeline_yaml: value }))}
        />
        <DraftPanel
          title="Job Definition"
          value={drafts.job_definition}
          onChange={(value) => setDrafts((current) => ({ ...current, job_definition: value }))}
        />
        <DraftPanel
          title="Published Fields"
          value={drafts.published_fields}
          onChange={(value) => setDrafts((current) => ({ ...current, published_fields: value }))}
        />
      </div>
    </section>
  );
}

function DraftPanel({
  title,
  value,
  onChange,
}: {
  title: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <section className="grid content-start gap-2 rounded-md border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
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
