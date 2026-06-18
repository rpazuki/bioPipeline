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
     
    mocked.listSavedDefinitions.mockResolvedValue([] as any);
     
    mocked.listAdminPublishedJobs.mockResolvedValue([] as any);
     
    mocked.listAdminPublishedRuns.mockResolvedValue([] as any);
     
    mocked.listAdminSharedRoots.mockResolvedValue([] as any);
    mocked.inspectPublishedJob.mockResolvedValue(
       
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

  it("seeds the default value from the job's Defaults section when a field is selected", async () => {
    const defaultCandidate = {
      id: "default_threshold",
      label: "Default: threshold",
      type: "integer",
      required: true,
      default: 5,
      help: "",
      example: "",
      options: [],
      bindings: [{ target: "definition_path", path: ["defaults", "threshold"] }],
      io_role: "none",
      accept: "file",
      sources: [],
      delivery: [],
      shared_roots: [],
    };
    mocked.listSavedDefinitions.mockResolvedValue([] as any);
    mocked.listAdminPublishedJobs.mockResolvedValue([] as any);
    mocked.listAdminPublishedRuns.mockResolvedValue([] as any);
    mocked.listAdminSharedRoots.mockResolvedValue([] as any);
    mocked.listTypeLibrary.mockResolvedValue({ types: [] } as any);
    mocked.inspectPublishedJob.mockResolvedValue({ job_name: "j", candidates: [defaultCandidate], warnings: [] } as any);
    render(<PublishedJobsAdminPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Inspect Fields" }));
    expect(await screen.findByText(/Valid definition/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    // The default editor is shown pre-filled with the value from the Defaults section.
    expect(await screen.findByDisplayValue("5")).toBeInTheDocument();
  });

  it("falls back to the example when a selected field has no real default", async () => {
    const exampleCandidate = {
      id: "stage_align_genome",
      label: "align: genome",
      type: "string",
      required: true,
      default: "",
      help: "",
      example: "GRCh38",
      options: [],
      bindings: [{ target: "stage_process_arg", stage: "align", process: "p", parameter: "genome" }],
      io_role: "none",
      accept: "file",
      sources: [],
      delivery: [],
      shared_roots: [],
    };
    mocked.listSavedDefinitions.mockResolvedValue([] as any);
    mocked.listAdminPublishedJobs.mockResolvedValue([] as any);
    mocked.listAdminPublishedRuns.mockResolvedValue([] as any);
    mocked.listAdminSharedRoots.mockResolvedValue([] as any);
    mocked.listTypeLibrary.mockResolvedValue({ types: [] } as any);
    mocked.inspectPublishedJob.mockResolvedValue({ job_name: "j", candidates: [exampleCandidate], warnings: [] } as any);
    render(<PublishedJobsAdminPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Inspect Fields" }));
    expect(await screen.findByText(/Valid definition/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    // No definition default, so the example seeds the pre-filled default value —
    // it now shows in both the Example input and the new Default value input.
    expect(await screen.findAllByDisplayValue("GRCh38")).toHaveLength(2);
  });

  it("hides the default value input for enum fields", async () => {
    mocked.listSavedDefinitions.mockResolvedValue([] as any);
    mocked.listAdminPublishedJobs.mockResolvedValue([] as any);
    mocked.listAdminPublishedRuns.mockResolvedValue([] as any);
    mocked.listAdminSharedRoots.mockResolvedValue([] as any);
    mocked.listTypeLibrary.mockResolvedValue({ types: [] } as any);
    mocked.inspectPublishedJob.mockResolvedValue({ job_name: "j", candidates: [variantCandidate], warnings: [] } as any);
    render(<PublishedJobsAdminPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Inspect Fields" }));
    expect(await screen.findByText(/Valid definition/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    // Editor opened (Example input present) but the Default value input is not.
    expect(await screen.findByText("Example")).toBeInTheDocument();
    expect(screen.queryByText(/Default value/)).not.toBeInTheDocument();
  });

  it("lets an admin mark a server-managed plain field as saveable", async () => {
    mocked.listSavedDefinitions.mockResolvedValue([] as any);
    mocked.listAdminPublishedJobs.mockResolvedValue([] as any);
    mocked.listAdminPublishedRuns.mockResolvedValue([] as any);
    mocked.listAdminSharedRoots.mockResolvedValue([] as any);
    mocked.listTypeLibrary.mockResolvedValue({ types: [] } as any);
    mocked.inspectPublishedJob.mockResolvedValue({ job_name: "j", candidates: [variantCandidate], warnings: [] } as any);
    render(<PublishedJobsAdminPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Inspect Fields" }));
    expect(await screen.findByText(/Valid definition/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    const saveable = await screen.findByRole("checkbox", { name: /Saveable/ });
    fireEvent.click(saveable);
    expect(saveable).toBeChecked();
  });
});
