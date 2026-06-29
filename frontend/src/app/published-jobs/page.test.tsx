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
    window.sessionStorage.clear(); // the form persists itself; isolate each test
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

  it("submits a url input as the field value without requiring an upload", async () => {
    const urlField = {
      id: "f1", label: "Data URL", type: "url", required: true, io_role: "input",
      accept: "file", sources: ["upload"], help: "", example: "https://example.test/raw.csv", options: [],
    };
    mocked.listPublishedJobs.mockResolvedValue([{ id: "J", name: "Job", description: "", version: 1 }] as any);
    mocked.getPublishedJob.mockResolvedValue(detail("J", "Job", [urlField]) as any);
    mocked.submitPublishedJobRun.mockResolvedValue({ id: "run1" } as any);

    render(<PublishedJobsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Version 1/ }));
    const input = await screen.findByPlaceholderText("https://example.test/raw.csv");
    fireEvent.change(input, { target: { value: "https://example.test/raw.csv" } });
    fireEvent.click(await screen.findByRole("button", { name: "Execute Job" }));

    await waitFor(() => expect(mocked.submitPublishedJobRun).toHaveBeenCalledTimes(1));
    expect(mocked.submitPublishedJobRun).toHaveBeenCalledWith(
      "J",
      expect.objectContaining({ f1: "https://example.test/raw.csv" }),
      null,
      { workspaceId: null, fileBindings: {} },
    );
  });

  it("enables browser autocomplete when the field opts in", async () => {
    const field = {
      id: "note", label: "Note", type: "string", required: false,
      default: "", help: "", example: "", options: [], autoompelete: true,
    };
    mocked.listPublishedJobs.mockResolvedValue([{ id: "J", name: "Job", description: "", version: 1 }] as any);
    mocked.getPublishedJob.mockResolvedValue(detail("J", "Job", [field]) as any);
    mocked.listSavedTypedValues.mockResolvedValue([] as any);

    render(<PublishedJobsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Job/ }));
    await screen.findByText("Selected Job");
    await waitFor(() => expect(document.querySelector('input[autocomplete="on"]')).not.toBeNull());
    const noteInput = document.querySelector('input[autocomplete="on"]');
    expect(noteInput).toBeTruthy();
    expect(noteInput).toHaveAttribute("autocomplete", "on");
  });

  it("restores the in-progress form after leaving and returning to the page", async () => {
    const field = {
      id: "note", label: "Note", type: "string", required: false,
      default: "", help: "", example: "", options: [],
    };
    mocked.listPublishedJobs.mockResolvedValue([{ id: "J", name: "Job", description: "", version: 1 }] as any);
    mocked.getPublishedJob.mockResolvedValue(detail("J", "Job", [field]) as any);
    mocked.listSavedTypedValues.mockResolvedValue([] as any);

    const first = render(<PublishedJobsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Job/ }));
    await screen.findByRole("button", { name: "Execute Job" }); // the field form has rendered
    // Type into the Note field (not the job-list filter box).
    const noteInput = screen
      .getAllByRole("textbox")
      .find((el) => (el as HTMLInputElement).placeholder !== "Search by name or description")!;
    fireEvent.change(noteInput, { target: { value: "hello world" } });
    // The form persists itself to sessionStorage as it changes.
    await waitFor(() => expect(window.sessionStorage.getItem("published-jobs:run-form")).toContain("hello world"));

    // Navigating to another page unmounts the component; React state is discarded.
    first.unmount();

    // Returning re-mounts it: the selected job and the typed value must come back without
    // re-selecting the job or re-typing.
    render(<PublishedJobsPage />);
    expect(await screen.findByDisplayValue("hello world")).toBeInTheDocument();
    expect(await screen.findByText("Selected Job")).toBeInTheDocument();
  });

  const SAVEABLE_FIELD = {
    id: "threshold", label: "Threshold", type: "integer", required: true,
    default: 5, saveable: true, io_role: "none", help: "", example: "", options: [],
  };

  function savedThreshold(value: string, updated_at: string) {
    return {
      id: "s1", type_key: "job:J:field:threshold:integer", container: "single",
      label: "Threshold", type_schema: {}, value_kind: "plain", field_schema: SAVEABLE_FIELD,
      value, created_at: "t0", updated_at,
    };
  }

  function seedSnapshot(values: Record<string, unknown>, savedBaseline: Record<string, string>) {
    window.sessionStorage.setItem("published-jobs:run-form", JSON.stringify({
      jobId: "J", values, shared: {}, scheduledAt: "", repeat: false,
      everyN: 1, unit: "days", endsMode: "never", endsCount: 10, endsAt: "", savedBaseline,
    }));
  }

  it("propagates a saved value edited elsewhere into the restored form", async () => {
    mocked.listPublishedJobs.mockResolvedValue([{ id: "J", name: "Job", description: "", version: 1 }] as any);
    mocked.getPublishedJob.mockResolvedValue(detail("J", "Job", [SAVEABLE_FIELD]) as any);
    // The saved value is now newer (42 @ t2) than what the snapshot recorded (baseline t1).
    mocked.listSavedTypedValues.mockResolvedValue([savedThreshold("42", "t2")] as any);
    seedSnapshot({ threshold: "7" }, { threshold: "t1" });

    render(<PublishedJobsPage />);
    // The restored form shows the edited saved value, not the snapshot's stale 7.
    expect(await screen.findByDisplayValue("42")).toBeInTheDocument();
  });

  it("keeps an in-progress edit when the saved value is unchanged", async () => {
    mocked.listPublishedJobs.mockResolvedValue([{ id: "J", name: "Job", description: "", version: 1 }] as any);
    mocked.getPublishedJob.mockResolvedValue(detail("J", "Job", [SAVEABLE_FIELD]) as any);
    // The saved value's updated_at matches the snapshot baseline → it did not change.
    mocked.listSavedTypedValues.mockResolvedValue([savedThreshold("7", "t1")] as any);
    // The researcher had typed 99 into the form (diverging from the saved 7).
    seedSnapshot({ threshold: "99" }, { threshold: "t1" });

    render(<PublishedJobsPage />);
    // The in-progress 99 survives — an unchanged saved value must not clobber it.
    expect(await screen.findByDisplayValue("99")).toBeInTheDocument();
  });

  it("saves an opted-in server-managed plain field", async () => {
    const field = {
      id: "threshold", label: "Threshold", type: "integer", required: true,
      default: 5, saveable: true, io_role: "none", help: "", example: "", options: [],
    };
    mocked.listPublishedJobs.mockResolvedValue([{ id: "J", name: "Job", description: "", version: 1 }] as any);
    mocked.getPublishedJob.mockResolvedValue(detail("J", "Job", [field]) as any);
    mocked.listSavedTypedValues.mockResolvedValue([] as any);
    mocked.saveTypedValue.mockResolvedValue({
      id: "saved", type_key: "job:J:field:threshold:integer", container: "single", label: "Threshold",
      type_schema: {}, value_kind: "plain", field_schema: field, value: "9",
    } as any);

    render(<PublishedJobsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Job/ }));
    fireEvent.change(await screen.findByRole("spinbutton"), { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(mocked.saveTypedValue).toHaveBeenCalledWith(expect.objectContaining({
      type_key: "job:J:field:threshold:integer",
      value_kind: "plain",
      value: "9",
    })));
  });
});
