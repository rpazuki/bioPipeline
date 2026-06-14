import { afterEach, describe, expect, it, vi } from "vitest";

import { browseSharedRoot, runArtifactUrl, uploadRunInput } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// A File-like stub: uploadRunInput only reads name/size and calls slice(), so we
// avoid allocating real megabytes of data.
function fakeFile(name: string, size: number): File {
  return {
    name,
    size,
    slice: (start: number, end: number) => ({ start, end }) as unknown as Blob,
  } as unknown as File;
}

describe("uploadRunInput chunking", () => {
  it("streams a single chunk for a small file", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ field_id: "f1", handle: "h", filename: "a.txt", size: 10 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await uploadRunInput("job1", "ws1", "f1", fakeFile("a.txt", 10));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.handle).toBe("h");
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/published-jobs/catalog/job1/runs/ws1/uploads/f1");
    expect(url).toContain("offset=0");
    expect(url).toContain("filename=a.txt");
    expect(fetchMock.mock.calls[0][1].credentials).toBe("include");
  });

  it("advances the offset across multiple 8MB chunks and preserves relpath", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ field_id: "f1", handle: "h", filename: "big.bin", size: 0 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const chunk = 8 * 1024 * 1024;
    await uploadRunInput("job1", "ws1", "f1", fakeFile("big.bin", chunk * 2 + 5), "sub/dir/big.bin");

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const offsets = fetchMock.mock.calls.map((c) => {
      const u = new URL(c[0] as string, "http://x");
      return u.searchParams.get("offset");
    });
    expect(offsets).toEqual(["0", String(chunk), String(chunk * 2)]);
    const firstUrl = new URL(fetchMock.mock.calls[0][0] as string, "http://x");
    expect(firstUrl.searchParams.get("relpath")).toBe("sub/dir/big.bin");
  });

  it("throws the server detail when a chunk upload fails", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 413,
      json: async () => ({ detail: "file too large" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(uploadRunInput("job1", "ws1", "f1", fakeFile("a.txt", 5))).rejects.toThrow(
      "file too large",
    );
  });
});

describe("URL helpers", () => {
  it("builds an encoded artifact URL", () => {
    expect(runArtifactUrl("run 1/x")).toBe("/api/v1/published-jobs/my-runs/run%201%2Fx/artifact");
  });

  it("encodes browse query parameters", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ root_id: "r", subpath: "", entries: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await browseSharedRoot("job1", "input", "shared", "a/b c");

    const url = new URL(fetchMock.mock.calls[0][0] as string, "http://x");
    expect(url.pathname).toBe("/api/v1/published-jobs/catalog/job1/browse");
    expect(url.searchParams.get("field")).toBe("input");
    expect(url.searchParams.get("root")).toBe("shared");
    expect(url.searchParams.get("subpath")).toBe("a/b c");
  });
});
