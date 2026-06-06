import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import JobDefinitionPanel from "./JobDefinitionPanel";
import * as api from "@/lib/api";

vi.mock("@/lib/api");

const mocked = vi.mocked(api);

describe("JobDefinitionPanel", () => {
  beforeEach(() => {
    mocked.listJobDefinitions.mockResolvedValue([
      { parent_job_id: "grp-1", job_name: "demo", status: "succeeded", total: 3, counts: { succeeded: 3 } },
    ]);
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
});
