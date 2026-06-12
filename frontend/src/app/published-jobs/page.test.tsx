import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PublishedJobsPage from "./page";
import * as api from "@/lib/api";

vi.mock("@/lib/api");
const mocked = vi.mocked(api);

// eslint-disable-next-line @typescript-eslint/no-explicit-any
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
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ] as any);
    mocked.getPublishedJob.mockImplementation(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
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

  it("keeps the uploaded file across submits so a re-run still binds it", async () => {
    const fileField = {
      id: "f1", label: "Data File", type: "file", required: true, io_role: "input",
      accept: "file", sources: ["upload"], help: "", example: "", options: [],
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mocked.listPublishedJobs.mockResolvedValue([{ id: "J", name: "Job", description: "", version: 1 }] as any);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mocked.getPublishedJob.mockResolvedValue(detail("J", "Job", [fileField]) as any);
    mocked.createDraftRun
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .mockResolvedValueOnce({ workspace_id: "ws1" } as any)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .mockResolvedValueOnce({ workspace_id: "ws2" } as any);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mocked.uploadRunInput.mockResolvedValue({ field_id: "f1", handle: "h", filename: "raw.csv", size: 4 } as any);
    mocked.submitPublishedJobRun
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .mockResolvedValueOnce({ id: "run1" } as any)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
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
