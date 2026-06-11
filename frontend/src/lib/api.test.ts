import { describe, expect, it, vi } from "vitest";

import { archiveDefinition, createUser, createYamlFolder, deletePipelineYaml, deleteSavedDefinition, deleteYamlFolder, disableUser, executeAITool, getAIContext, getCurrentUser, getJobDefinition, getPipelineYaml, installPackage, listJobDefinitions, listPackages, listSavedDefinitions, listUsers, login, logout, movePipelineYaml, previewJobDefinition, resetUserPassword, restoreDefinition, saveDefinition, savePipelineYaml, sendAIChatMessage, submitJob, submitJobDefinition, testAIProvider, uninstallPackage, updateUser, validateYamlContent } from "./api";

function mockFetch(payload: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => payload,
    // The AI chat client reads the streamed body as text and parses the last
    // line; expose the payload as a single JSON line for that path.
    text: async () => JSON.stringify(payload),
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
    expect(fetchMock.mock.calls[0][1].credentials).toBe("include");
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

  it("uses session-backed package endpoints", async () => {
    const fetchMock = mockFetch({ installed: [], history: [] });

    await listPackages();
    await installPackage("labUtils", "git");
    await uninstallPackage("labUtils");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/packages");

    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/packages/install");
    const installBody = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(installBody).toEqual({ spec: "labUtils", source_type: "git" });

    expect(fetchMock.mock.calls[2][0]).toBe("/api/v1/packages/uninstall");
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ name: "labUtils" });
  });

  it("targets auth and user-management endpoints", async () => {
    const fetchMock = mockFetch({ user: { id: "u1", username: "admin", role: "admin" } });

    await login("admin", "password123");
    await getCurrentUser();
    await logout();
    await listUsers();
    await createUser({ username: "worker", password: "password123", role: "user" });
    await updateUser("u1", { display_name: "Admin" });
    await resetUserPassword("u1", "newpass123");
    await disableUser("u1");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/auth/login");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/auth/me");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/v1/auth/logout");
    expect(fetchMock.mock.calls[3][0]).toBe("/api/v1/users");
    expect(fetchMock.mock.calls[4][0]).toBe("/api/v1/users");
    expect(fetchMock.mock.calls[5][0]).toBe("/api/v1/users/u1");
    expect(fetchMock.mock.calls[6][0]).toBe("/api/v1/users/u1/reset-password");
    expect(fetchMock.mock.calls[7][0]).toBe("/api/v1/users/u1/disable");
  });

  it("targets the job-definition store endpoints", async () => {
    const fetchMock = mockFetch([]);

    await listSavedDefinitions();
    await saveDefinition("designs/growth.yaml", "job: x");
    await archiveDefinition("designs/growth.yaml");
    await restoreDefinition("designs/growth.yaml");
    await deleteSavedDefinition("designs/growth.yaml", true);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/job-definition-store");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/job-definition-store");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      name: "designs/growth.yaml",
      content: "job: x",
      overwrite: true,
    });
    expect(fetchMock.mock.calls[2][0]).toBe("/api/v1/job-definition-store/designs/growth.yaml/archive");
    expect(fetchMock.mock.calls[3][0]).toBe("/api/v1/job-definition-store/designs/growth.yaml/restore");
    expect(fetchMock.mock.calls[4][0]).toBe("/api/v1/job-definition-store/designs/growth.yaml?archived=true");
  });

  it("targets the AI designer endpoints without leaking keys", async () => {
    const fetchMock = mockFetch({ providers: [], tools: [], message: { role: "assistant", content: "" }, tool_calls: [], drafts: [] });

    await getAIContext();
    await testAIProvider({ provider: "claude" });
    await sendAIChatMessage({ messages: [{ role: "user", content: "hello" }], confirmations: {} });
    await executeAITool("validate_pipeline_yaml", { content: "pipelines: []" }, true);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/ai-chat/context");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/ai-chat/test-provider");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ provider: "claude" });
    expect(fetchMock.mock.calls[2][0]).toBe("/api/v1/ai-chat/messages");
    expect(JSON.parse(fetchMock.mock.calls[2][1].body).messages[0].content).toBe("hello");
    expect(fetchMock.mock.calls[3][0]).toBe("/api/v1/ai-chat/tools/execute");
    expect(JSON.parse(fetchMock.mock.calls[3][1].body)).toEqual({
      name: "validate_pipeline_yaml",
      arguments: { content: "pipelines: []" },
      confirmed: true,
    });
  });
});
