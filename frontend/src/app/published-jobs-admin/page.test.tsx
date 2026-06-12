import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PublishedJobsAdminPage from "./page";
import * as api from "@/lib/api";

vi.mock("@/lib/api");
const mocked = vi.mocked(api);

const variantCandidate = {
  id: "var_variant",
  label: "Variable: variant",
  type: "enum",
  required: true,
  default: { name: "a", pipeline: "p_a" },
  help: "",
  example: "",
  options: [{ label: "a", value: { name: "a", pipeline: "p_a" } }],
  bindings: [{ target: "definition_path", path: ["variables", "variant"] }],
  io_role: "none",
  accept: "file",
  sources: [],
  delivery: [],
  shared_roots: [],
};

describe("PublishedJobsAdminPage field editor", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows the definition-derived origin read-only and keeps it after the label is renamed", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mocked.listSavedDefinitions.mockResolvedValue([] as any);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mocked.listAdminPublishedJobs.mockResolvedValue([] as any);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mocked.listAdminPublishedRuns.mockResolvedValue([] as any);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mocked.listAdminSharedRoots.mockResolvedValue([] as any);
    mocked.inspectPublishedJob.mockResolvedValue(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      { job_name: "j", candidates: [variantCandidate], warnings: [] } as any,
    );

    render(<PublishedJobsAdminPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Inspect Fields" }));

    // The status message is shown below the action buttons after inspecting.
    expect(await screen.findByText(/Valid definition/)).toBeInTheDocument();
    // The stable origin is shown (read-only) even before the field is selected.
    expect(await screen.findByText("Variable: variant")).toBeInTheDocument();

    // Select the field; the editable label defaults to the origin, then rename it.
    fireEvent.click(screen.getByRole("checkbox"));
    const labelInput = await screen.findByDisplayValue("Variable: variant");
    fireEvent.change(labelInput, { target: { value: "Averaging method" } });

    // The renamed label applies, but the origin stays visible for orientation.
    expect(screen.getByDisplayValue("Averaging method")).toBeInTheDocument();
    expect(screen.getByText("Variable: variant")).toBeInTheDocument();
  });
});
