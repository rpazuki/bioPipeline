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

  it("shows a Default URL input when an input field is set to url mode", async () => {
    const fileCandidate = {
      id: "raw_data",
      label: "run: input raw_data",
      type: "file",
      required: true,
      default: "",
      help: "",
      example: "",
      options: [],
      bindings: [{ target: "stage_input_source", stage: "run", input: "raw_data" }],
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
    mocked.inspectPublishedJob.mockResolvedValue({ job_name: "j", candidates: [fileCandidate], warnings: [] } as any);
    render(<PublishedJobsAdminPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Inspect Fields" }));
    fireEvent.click(await screen.findByRole("checkbox"));

    fireEvent.change(await screen.findByLabelText("Researcher handling"), { target: { value: "input" } });
    // No URL default field for a plain file input…
    expect(screen.queryByLabelText(/Default URL/)).not.toBeInTheDocument();
    // …but it appears once the input accepts a URL, and is editable.
    fireEvent.change(await screen.findByLabelText("Accepts"), { target: { value: "url" } });
    const urlDefault = await screen.findByLabelText(/Default URL/);
    fireEvent.change(urlDefault, { target: { value: "https://example.org/data.csv" } });
    expect(urlDefault).toHaveValue("https://example.org/data.csv");
  });

  it("offers built-in structured collection types for a server-managed field", async () => {
    const objectCandidate = {
      id: "default_opts",
      label: "Default: opts",
      type: "object",
      required: true,
      default: {},
      help: "",
      example: "",
      options: [],
      bindings: [{ target: "definition_path", path: ["defaults", "opts"] }],
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
    mocked.inspectPublishedJob.mockResolvedValue({ job_name: "j", candidates: [objectCandidate], warnings: [] } as any);
    render(<PublishedJobsAdminPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Inspect Fields" }));
    fireEvent.click(await screen.findByRole("checkbox"));

    const structured = await screen.findByLabelText("Structured type");
    // Built-in add/remove collections are available with no library type defined.
    expect(screen.getByRole("option", { name: "List of text" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Named map of decimals" })).toBeInTheDocument();
    // Selecting one turns the field typed — the plain-only "Saveable" toggle disappears.
    expect(screen.getByRole("checkbox", { name: /Saveable/ })).toBeInTheDocument();
    fireEvent.change(structured, { target: { value: "builtin:list:string" } });
    expect(screen.queryByRole("checkbox", { name: /Saveable/ })).not.toBeInTheDocument();
  });

  it("keeps an inline structured field typed after reloading a saved job for edit", async () => {
    // Regression guard: on Edit, saved fields are re-merged against fresh (plain)
    // candidates. An inline built-in collection carries its own type_schema (which is
    // NOT a curated key), so mergeFields must re-attach it — otherwise the field
    // reverts to a plain value and the next save drops the researcher's editor.
    const binding = { target: "definition_path", path: ["defaults", "opts"] };
    const inlineField = {
      id: "opts",
      label: "Options",
      type: "typed",
      schema_ref: "",
      container: "list",
      type_schema: { name: "List of text", kind: "scalar", scalar: { type: "string", options: [], help: "", example: "" } },
      default: [],
      help: "",
      example: "",
      options: [],
      bindings: [binding],
      io_role: "none",
      accept: "file",
      sources: [],
      delivery: [],
      shared_roots: [],
    };
    const plainCandidate = {
      id: "opts",
      label: "Default: opts",
      type: "object",
      required: true,
      default: {},
      help: "",
      example: "",
      options: [],
      bindings: [binding],
      io_role: "none",
      accept: "file",
      sources: [],
      delivery: [],
      shared_roots: [],
    };
    const savedJob = {
      id: "job1",
      name: "Saved job",
      description: "",
      status: "published",
      version: 1,
      definition_name: "d.yaml",
      definition_content: "job: d",
      fields: [inlineField],
      created_at: "",
      updated_at: "",
      created_by: "admin",
      updated_by: "admin",
    };
    mocked.listSavedDefinitions.mockResolvedValue([] as any);
    mocked.listAdminPublishedJobs.mockResolvedValue([savedJob] as any);
    mocked.listAdminPublishedRuns.mockResolvedValue([] as any);
    mocked.listAdminPublishedJobRuns.mockResolvedValue([] as any);
    mocked.listAdminSharedRoots.mockResolvedValue([] as any);
    mocked.listTypeLibrary.mockResolvedValue({ types: [] } as any);
    mocked.getAdminPublishedJob.mockResolvedValue(savedJob as any);
    mocked.inspectPublishedJob.mockResolvedValue({ job_name: "Saved job", candidates: [plainCandidate], warnings: [] } as any);
    render(<PublishedJobsAdminPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    // The rebuilt field still carries its inline collection binding, not "plain value".
    const structured = await screen.findByLabelText("Structured type");
    expect(structured).toHaveValue("builtin:list:string");
  });

  it("lets an admin opt an input field into url mode and autocomplete", async () => {
    const fileCandidate = {
      id: "raw_data",
      label: "run: input raw_data",
      type: "file",
      required: true,
      default: "",
      help: "",
      example: "",
      options: [],
      bindings: [{ target: "stage_input_source", stage: "run", input: "raw_data" }],
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
    mocked.inspectPublishedJob.mockResolvedValue({ job_name: "j", candidates: [fileCandidate], warnings: [] } as any);
    render(<PublishedJobsAdminPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Inspect Fields" }));
    fireEvent.click(await screen.findByRole("checkbox"));

    fireEvent.change(await screen.findByLabelText("Researcher handling"), { target: { value: "input" } });
    expect(await screen.findByRole("option", { name: "A URL or upload a file" })).toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText("Accepts"), { target: { value: "url" } });

    const autocomplete = await screen.findByRole("checkbox", { name: /Autocomplete/ });
    fireEvent.click(autocomplete);
    expect(autocomplete).toBeChecked();
  });
});
