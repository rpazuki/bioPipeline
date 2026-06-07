import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import JobDefinitionPanel from "./JobDefinitionPanel";
import * as api from "@/lib/api";

vi.mock("@/lib/api");

// The stage DAG renders ReactFlow, which needs ResizeObserver (absent in jsdom);
// stub it so the panel's other behaviour can be tested.
vi.mock("@/components/pipelines/JobStageGraph", () => ({ default: () => null }));

const pipelineContextState = vi.hoisted(() => ({
  jobDefinitionDraft: null as { name: string; content: string } | null,
  jobDefinitionName: null as string | null,
  jobDefinitionContent: "",
  setJobDefinitionDraft: vi.fn(),
  setJobDefinitionName: vi.fn(),
  setJobDefinitionContent: vi.fn(),
  setStatus: vi.fn(),
}));

// Avoid needing a PipelineProvider in the test.
vi.mock("@/components/pipelines/PipelineContext", async () => {
  const React = await import("react");
  return {
    usePipeline: () => {
      const [jobDefinitionDraft, setJobDefinitionDraftState] = React.useState<
        { name: string; content: string } | null
      >(pipelineContextState.jobDefinitionDraft);
      const [jobDefinitionName, setJobDefinitionNameState] = React.useState<string | null>(
        pipelineContextState.jobDefinitionName,
      );
      const [jobDefinitionContent, setJobDefinitionContentState] = React.useState(
        pipelineContextState.jobDefinitionContent,
      );
      return {
        jobDefinitionDraft,
        jobDefinitionName,
        jobDefinitionContent,
        setJobDefinitionDraft: (value: { name: string; content: string } | null) => {
          pipelineContextState.setJobDefinitionDraft(value);
          setJobDefinitionDraftState(value);
        },
        setJobDefinitionName: (value: string | null) => {
          pipelineContextState.setJobDefinitionName(value);
          setJobDefinitionNameState(value);
        },
        setJobDefinitionContent: (value: string) => {
          pipelineContextState.setJobDefinitionContent(value);
          setJobDefinitionContentState(value);
        },
        setStatus: pipelineContextState.setStatus,
      };
    },
  };
});

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const mocked = vi.mocked(api);

describe("JobDefinitionPanel", () => {
  beforeEach(() => {
    mocked.listJobDefinitions.mockResolvedValue([
      { parent_job_id: "grp-1", job_name: "demo", status: "succeeded", total: 3, counts: { succeeded: 3 } },
    ]);
    // Default so the debounced auto-preview always has something to resolve.
    mocked.previewJobDefinition.mockResolvedValue({ job_name: "", task_count: 0, tasks: [] });
    mocked.listJobDefinitionTemplates.mockResolvedValue([
      { name: "empty", description: "Minimal one-stage shell." },
    ]);
    mocked.listPipelineYamls.mockResolvedValue([
      { name: "demo.yaml", pipelines: ["pipeline_a", "pipeline_b"], is_valid: true },
    ]);
    pipelineContextState.jobDefinitionDraft = null;
    pipelineContextState.jobDefinitionName = null;
    pipelineContextState.jobDefinitionContent = "";
    pipelineContextState.setJobDefinitionDraft.mockClear();
    pipelineContextState.setJobDefinitionName.mockClear();
    pipelineContextState.setJobDefinitionContent.mockClear();
    pipelineContextState.setStatus.mockClear();
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("lists submitted job groups on mount", async () => {
    render(<JobDefinitionPanel />);
    expect(await screen.findByText("demo")).toBeInTheDocument();
    expect(screen.getByText("succeeded")).toBeInTheDocument();
  });

  it("previews the definition and shows the expanded tasks", async () => {
    mocked.previewJobDefinition.mockResolvedValue({
      job_name: "demo",
      task_count: 2,
      tasks: [
        {
          job_name: "demo",
          stage: "preprocess",
          matrix_key: { run_tag: "A" },
          needs: [],
          pipeline_yaml: "g.yaml",
          pipeline_name: "fit",
          output_dir: "/out/A",
          input_sources: {},
          process_arg_mapping: {},
          item_index: 0,
        },
        {
          job_name: "demo",
          stage: "collate",
          matrix_key: { run_tag: "A" },
          needs: ["preprocess"],
          pipeline_yaml: "c.yaml",
          pipeline_name: "collate",
          output_dir: "/out/A_STRAINS",
          input_sources: {},
          process_arg_mapping: {},
          item_index: 0,
        },
      ],
    });

    render(<JobDefinitionPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    await waitFor(() => expect(mocked.previewJobDefinition).toHaveBeenCalled());
    expect(await screen.findByText(/Preview — 2 tasks/)).toBeInTheDocument();
    expect(screen.getByText("[preprocess]")).toBeInTheDocument();
    expect(screen.getByText("[collate]")).toBeInTheDocument();
  });

  it("surfaces API errors from preview", async () => {
    mocked.previewJobDefinition.mockRejectedValue(new Error("bad definition"));

    render(<JobDefinitionPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    expect(await screen.findByText("bad definition")).toBeInTheDocument();
  });

  it("loads a selected template into the editor", async () => {
    mocked.getJobDefinitionTemplate.mockResolvedValue({
      name: "empty",
      description: "Minimal one-stage shell.",
      content: "job: from_template\nstages: []\n",
    });

    render(<JobDefinitionPanel />);
    await screen.findByRole("option", { name: "empty" });
    fireEvent.change(screen.getByLabelText("Job definition template"), { target: { value: "empty" } });

    await waitFor(() => expect(mocked.getJobDefinitionTemplate).toHaveBeenCalledWith("empty"));
    expect(await screen.findByDisplayValue(/job: from_template/)).toBeInTheDocument();
  });

  it("navigates to the Job Queue after a successful submit", async () => {
    mocked.submitJobDefinition.mockResolvedValue({
      parent_job_id: "grp-9",
      job_name: "demo",
      status: "queued",
      total: 1,
      counts: { queued: 1 },
      tasks: [],
    });

    render(<JobDefinitionPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(mocked.submitJobDefinition).toHaveBeenCalled());
    expect(push).toHaveBeenCalledWith("/");
  });

  it("saves opened storage definitions back to the same name", async () => {
    pipelineContextState.jobDefinitionDraft = {
      name: "saved/demo.yaml",
      content: "job: saved_demo\nstages:\n  - name: first\n    pipeline_yaml: demo.yaml\n    pipeline: pipeline_a\n    output_dir: /out\n",
    };
    mocked.saveDefinition.mockResolvedValue({
      name: "saved/demo.yaml",
      job: "saved_demo",
      content: pipelineContextState.jobDefinitionDraft.content,
      is_valid: true,
    });

    render(<JobDefinitionPanel />);
    expect(await screen.findByText("Editing saved/demo.yaml")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Job Definition YAML"), {
      target: { value: "job: saved_demo\nstages:\n  - name: edited\n    pipeline_yaml: demo.yaml\n    pipeline: pipeline_a\n    output_dir: /out\n" },
    });
    await waitFor(() => expect(screen.getByDisplayValue(/name: edited/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));

    await waitFor(() => expect(mocked.saveDefinition).toHaveBeenCalled());
    expect(mocked.saveDefinition).toHaveBeenCalledWith(
      "saved/demo.yaml",
      expect.stringContaining("name: edited"),
    );
  });

  it("appends a selected pipeline as a new dependent stage", async () => {
    render(<JobDefinitionPanel />);
    await screen.findByText("Add Stage From Pipeline");

    fireEvent.change(screen.getByLabelText("Stage name"), { target: { value: "second" } });
    fireEvent.change(screen.getByLabelText("Pipeline"), { target: { value: "pipeline_b" } });
    fireEvent.click(await screen.findByLabelText("preprocess"));
    fireEvent.click(screen.getByRole("button", { name: "Add Stage" }));

    const editor = await screen.findByLabelText("Job Definition YAML");
    expect((editor as HTMLTextAreaElement).value).toContain("name: second");
    expect((editor as HTMLTextAreaElement).value).toContain("pipeline: pipeline_b");
    expect((editor as HTMLTextAreaElement).value).toContain("needs:");
    expect((editor as HTMLTextAreaElement).value).toContain("- preprocess");
  });
});
