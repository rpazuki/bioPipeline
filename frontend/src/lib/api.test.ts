import { describe, expect, it, vi } from "vitest";

import { createYamlFolder, deletePipelineYaml, deleteYamlFolder, getJobDefinition, getPipelineYaml, listJobDefinitions, movePipelineYaml, previewJobDefinition, savePipelineYaml, submitJob, submitJobDefinition, validateYamlContent } from "./api";

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

  it("encodes nested YAML and folder paths by segment", async () => {
    const fetchMock = mockFetch({});

    await getPipelineYaml("designs/alpha/demo pipeline.yaml");
    await createYamlFolder("designs/alpha");
    await deleteYamlFolder("designs/alpha");
    await movePipelineYaml("designs/alpha/demo.yaml", "designs/beta/demo.yaml");
    await deletePipelineYaml("designs/beta/demo.yaml");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/pipeline-yamls/designs/alpha/demo%20pipeline.yaml");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/pipeline-yamls/folders");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/v1/pipeline-yamls/folders/designs/alpha");
    expect(fetchMock.mock.calls[3][0]).toBe("/api/v1/pipeline-yamls/move");
    expect(fetchMock.mock.calls[4][0]).toBe("/api/v1/pipeline-yamls/designs/beta/demo.yaml");
  });

  it("targets the job-definition endpoints", async () => {
    const fetchMock = mockFetch({ tasks: [] });

    await previewJobDefinition("job: x");
    await submitJobDefinition("job: x");
    await listJobDefinitions();
    await getJobDefinition("grp-1");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/job-definitions/preview");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/job-definitions");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).content).toBe("job: x");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/v1/job-definitions");
    expect(fetchMock.mock.calls[3][0]).toBe("/api/v1/job-definitions/grp-1");
  });
});

