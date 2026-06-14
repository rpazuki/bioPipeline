import { afterEach, describe, expect, it, vi } from "vitest";

import {
  UNAUTHORIZED_EVENT,
  deletePipelineYaml,
  getCurrentUser,
  listJobs,
  login,
  sendAIChatMessage,
} from "./api";

// These tests exercise the cross-cutting behaviour of `apiFetch` and the
// streaming `sendAIChatMessage` parser — the timeout, 401, 5xx and 204 paths
// that the routing-focused api.test.ts does not touch.

type FetchResponse = {
  ok: boolean;
  status: number;
  json?: () => Promise<unknown>;
  text?: () => Promise<string>;
};

function stubFetchResponse(response: FetchResponse) {
  const fetchMock = vi.fn().mockResolvedValue({
    json: async () => ({}),
    text: async () => "",
    ...response,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("apiFetch error handling", () => {
  it("returns undefined for a 204 No Content response without parsing a body", async () => {
    const json = vi.fn();
    stubFetchResponse({ ok: true, status: 204, json });

    const result = await deletePipelineYaml("demo.yaml");

    expect(result).toBeUndefined();
    expect(json).not.toHaveBeenCalled();
  });

  it("throws the backend-provided detail message verbatim", async () => {
    stubFetchResponse({
      ok: false,
      status: 400,
      json: async () => ({ detail: "pipeline name already exists" }),
    });

    await expect(listJobs()).rejects.toThrow("pipeline name already exists");
  });

  it("surfaces a generic status message when no detail is provided", async () => {
    stubFetchResponse({ ok: false, status: 404, json: async () => ({}) });

    await expect(listJobs()).rejects.toThrow("API error 404");
  });

  it("explains an opaque 5xx as a likely dev-proxy timeout", async () => {
    stubFetchResponse({ ok: false, status: 500, json: async () => ({}) });

    await expect(listJobs()).rejects.toThrow(/dev proxy timed out|backend restarted/);
  });

  it("dispatches the unauthorized event on a 401 outside the login call", async () => {
    stubFetchResponse({ ok: false, status: 401, json: async () => ({}) });
    const listener = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, listener);

    await expect(getCurrentUser()).rejects.toThrow();
    expect(listener).toHaveBeenCalledTimes(1);

    window.removeEventListener(UNAUTHORIZED_EVENT, listener);
  });

  it("does NOT dispatch the unauthorized event for a failed login attempt", async () => {
    stubFetchResponse({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Invalid credentials" }),
    });
    const listener = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, listener);

    await expect(login("admin", "wrong")).rejects.toThrow("Invalid credentials");
    expect(listener).not.toHaveBeenCalled();

    window.removeEventListener(UNAUTHORIZED_EVENT, listener);
  });

  it("translates an aborted (timed-out) request into a friendly timeout error", async () => {
    const abortError = Object.assign(new Error("aborted"), { name: "AbortError" });
    const fetchMock = vi.fn().mockRejectedValue(abortError);
    vi.stubGlobal("fetch", fetchMock);

    await expect(listJobs()).rejects.toThrow(/timed out after \d+s/);
  });
});

describe("sendAIChatMessage streaming parser", () => {
  function stubChatText(text: string, ok = true, status = 200) {
    const fetchMock = vi.fn().mockResolvedValue({
      ok,
      status,
      json: async () => JSON.parse(text || "{}"),
      text: async () => text,
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  const request = { messages: [{ role: "user" as const, content: "hi" }], confirmations: {} };

  it("ignores heartbeat blank lines and parses the final JSON line", async () => {
    const payload = { message: { role: "assistant", content: "done" }, tool_calls: [], drafts: [] };
    stubChatText(`\n\n   \n${JSON.stringify(payload)}\n`);

    const result = await sendAIChatMessage(request);

    expect(result.message.content).toBe("done");
  });

  it("throws when the streamed body is empty", async () => {
    stubChatText("\n   \n\n");

    await expect(sendAIChatMessage(request)).rejects.toThrow(/empty response/);
  });

  it("throws a clear error when the final line is malformed JSON", async () => {
    stubChatText("not json at all");

    await expect(sendAIChatMessage(request)).rejects.toThrow(/malformed response/);
  });

  it("surfaces an in-band error payload's detail", async () => {
    stubChatText(JSON.stringify({ error: { status: 500, detail: "provider exploded" } }));

    await expect(sendAIChatMessage(request)).rejects.toThrow("provider exploded");
  });

  it("dispatches the unauthorized event for an in-band 401 error payload", async () => {
    stubChatText(JSON.stringify({ error: { status: 401, detail: "session expired" } }));
    const listener = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, listener);

    await expect(sendAIChatMessage(request)).rejects.toThrow("session expired");
    expect(listener).toHaveBeenCalledTimes(1);

    window.removeEventListener(UNAUTHORIZED_EVENT, listener);
  });

  it("dispatches the unauthorized event for a pre-stream 401 response", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: "no session" }),
      text: async () => "",
    });
    vi.stubGlobal("fetch", fetchMock);
    const listener = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, listener);

    await expect(sendAIChatMessage(request)).rejects.toThrow("no session");
    expect(listener).toHaveBeenCalledTimes(1);

    window.removeEventListener(UNAUTHORIZED_EVENT, listener);
  });
});
