import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import TypeLibraryPanel from "./TypeLibraryPanel";
import * as api from "@/lib/api";

vi.mock("@/lib/api");
const mocked = vi.mocked(api);

// A type whose enum field carries {label, value} options — the shape an extracted enum
// (e.g. labUtils EnumerationMode) produces.
const ENUM_TYPE = {
  name: "EnumerationConfig",
  description: "",
  fields: {
    mode: {
      type: "enum",
      required: false,
      options: [
        { label: "CARTESIAN", value: "cartesian" },
        { label: "CUSTOM", value: "custom" },
      ],
    },
  },
};

describe("TypeLibraryPanel enum option round-trip", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("preserves {label,value} enum options through an edit instead of corrupting them", async () => {
    mocked.listTypeLibrary.mockResolvedValue({ types: [ENUM_TYPE] } as any);
    mocked.upsertType.mockResolvedValue(ENUM_TYPE as any);

    render(<TypeLibraryPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));

    // The options round-trip as `LABEL=value`, never the stringified "[object Object]".
    expect(screen.getByDisplayValue("CARTESIAN=cartesian, CUSTOM=custom")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save type" }));

    await waitFor(() => expect(mocked.upsertType).toHaveBeenCalled());
    const [name, body] = mocked.upsertType.mock.calls[0];
    expect(name).toBe("EnumerationConfig");
    expect((body.fields as any).mode.options).toEqual([
      { label: "CARTESIAN", value: "cartesian" },
      { label: "CUSTOM", value: "custom" },
    ]);
  });

  it("sends the multiple flag when the box is checked", async () => {
    mocked.listTypeLibrary.mockResolvedValue({ types: [ENUM_TYPE] } as any);
    mocked.upsertType.mockResolvedValue(ENUM_TYPE as any);

    render(<TypeLibraryPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Allow multiple saved cases/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save type" }));

    await waitFor(() => expect(mocked.upsertType).toHaveBeenCalled());
    expect(mocked.upsertType.mock.calls[0][1].multiple).toBe(true);
  });
});
