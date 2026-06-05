import { describe, expect, it, vi } from "vitest";

import { savePipelineYaml, submitJob, validateYamlContent } from "./api";

function mockFetch(payload: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => payload,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("pipeline API client", () => {
  it("separates storage, validation, and execution endpoints", async () => {
    const fetchMock = mockFetch({});

    await savePipelineYaml("demo.yaml", "pipelines: []");
    await validateYamlContent("pipelines: []");
    await submitJob({
      yaml_name: "demo.yaml",
      pipeline_name: "demo",
      output_dir: "./outputs",
      input_sources: {},
    });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/pipeline-yamls");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/validation/yaml");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/v1/jobs");
  });
});

