import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PublishedJobsPage from "./page";
import * as api from "@/lib/api";

vi.mock("@/lib/api");
const mocked = vi.mocked(api);

 
function detail(id: string, name: string, fields: any[] = []) {
  return { id, name, description: "", version: 1, fields };
}

describe("PublishedJobsPage", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("clears a prior error when another job is selected", async () => {
    mocked.listPublishedJobs.mockResolvedValue([
      { id: "A", name: "Job A", description: "", version: 1 },
      { id: "B", name: "Job B", description: "", version: 1 },
       
    ] as any);
    mocked.getPublishedJob.mockImplementation(
       
      async (id: string) => detail(id, id === "A" ? "Job A" : "Job B") as any,
    );
    mocked.submitPublishedJobRun.mockRejectedValue(new Error("submit failed"));

    render(<PublishedJobsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Job A/ }));
    const execute = await screen.findByRole("button", { name: "Execute Job" });
    // The status message is shown below the Execute Job button.
    expect(screen.getByText("Selected Job A")).toBeInTheDocument();
    fireEvent.click(execute);
    expect(await screen.findByText("submit failed")).toBeInTheDocument();

    // Switching jobs must not carry the previous job's error over.
    fireEvent.click(screen.getByRole("button", { name: /Job B/ }));
    await waitFor(() => expect(screen.queryByText("submit failed")).not.toBeInTheDocument());
  });

  it("starts a typed field as an empty container even when its default is a scalar", async () => {
    // Regression: a typed field whose admin default is a scalar (e.g. the type name)
    // must NOT submit that scalar — the backend then rejects it ("must be a map of …").
    const typedField = {
      id: "rules", label: "Rules", type: "typed", required: true,
      default: "CustomReplicateRule", help: "", example: "", options: [],
      container: "map",

      type_schema: { name: "CustomReplicateRule", fields: [
        { name: "sample_size", type: "integer", container: "single", required: false, options: [] },
      ] },
    };

    mocked.listPublishedJobs.mockResolvedValue([{ id: "J", name: "Typed Job", description: "", version: 1 }] as any);

    mocked.getPublishedJob.mockResolvedValue(detail("J", "Typed Job", [typedField]) as any);

    mocked.listSavedTypedValues.mockResolvedValue([] as any); // no saved value → default path

    mocked.submitPublishedJobRun.mockResolvedValue({ id: "run1" } as any);

    render(<PublishedJobsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Typed Job/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Execute Job" }));

    await waitFor(() => expect(mocked.submitPublishedJobRun).toHaveBeenCalledTimes(1));
    const submittedValues = mocked.submitPublishedJobRun.mock.calls[0][1] as Record<string, unknown>;
    expect(submittedValues.rules).toEqual({}); // empty map, not the "CustomReplicateRule" string
  });

  it("keeps the uploaded file across submits so a re-run still binds it", async () => {
    const fileField = {
      id: "f1", label: "Data File", type: "file", required: true, io_role: "input",
      accept: "file", sources: ["upload"], help: "", example: "", options: [],
    };
     
    mocked.listPublishedJobs.mockResolvedValue([{ id: "J", name: "Job", description: "", version: 1 }] as any);
     
    mocked.getPublishedJob.mockResolvedValue(detail("J", "Job", [fileField]) as any);
    mocked.createDraftRun
       
      .mockResolvedValueOnce({ workspace_id: "ws1" } as any)
       
      .mockResolvedValueOnce({ workspace_id: "ws2" } as any);
     
    mocked.uploadRunInput.mockResolvedValue({ field_id: "f1", handle: "h", filename: "raw.csv", size: 4 } as any);
    mocked.submitPublishedJobRun
       
      .mockResolvedValueOnce({ id: "run1" } as any)
       
      .mockResolvedValueOnce({ id: "run2" } as any);

    const { container } = render(<PublishedJobsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Version 1/ }));
    await screen.findByRole("button", { name: "Execute Job" });

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["data"], "raw.csv", { type: "text/csv" })] } });

    fireEvent.click(screen.getByRole("button", { name: "Execute Job" }));
    await waitFor(() => expect(mocked.submitPublishedJobRun).toHaveBeenCalledTimes(1));

    // Second run WITHOUT re-picking the file: the selection must persist and re-bind.
    fireEvent.click(screen.getByRole("button", { name: "Execute Job" }));
    await waitFor(() => expect(mocked.submitPublishedJobRun).toHaveBeenCalledTimes(2));

    const secondOpts = mocked.submitPublishedJobRun.mock.calls[1][3] as { fileBindings: Record<string, unknown> };
    expect(secondOpts.fileBindings.f1).toEqual({ kind: "upload", path: "h" });
  });
});
