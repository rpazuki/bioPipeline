import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SavedCasesControl from "./SavedCasesControl";

function mkCase(id: string, name: string, is_default: boolean) {
  return {
    id, type_key: "Rule", container: "single", name, is_default, multiple: true, label: "Rule",
    type_schema: {}, value_kind: "typed", field_schema: {}, value: {}, created_at: "t", updated_at: "t",
  };
}

describe("SavedCasesControl", () => {
  afterEach(cleanup);

  const cases = [mkCase("a", "SLAB", true), mkCase("b", "WT", false)];

  function renderControl(overrides: Partial<Record<string, unknown>> = {}) {
    const handlers = {
      onSelect: vi.fn(), onAdd: vi.fn(), onRename: vi.fn(), onSetDefault: vi.fn(), onDelete: vi.fn(),
    };
    render(
      <SavedCasesControl
        cases={cases as any}
        selectedId="b"
        {...handlers}
        {...(overrides as any)}
      />,
    );
    return handlers;
  }

  it("switches the active case", () => {
    const handlers = renderControl();
    fireEvent.change(screen.getByRole("combobox", { name: "Saved case" }), { target: { value: "a" } });
    expect(handlers.onSelect).toHaveBeenCalledWith("a");
  });

  it("sets the selected non-default case as default", () => {
    const handlers = renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Set default" }));
    expect(handlers.onSetDefault).toHaveBeenCalledWith("b");
  });

  it("disables the default button for the default case", () => {
    renderControl({ selectedId: "a" });
    expect(screen.getByRole("button", { name: "Default" })).toBeDisabled();
  });

  it("deletes the selected case", () => {
    const handlers = renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(handlers.onDelete).toHaveBeenCalledWith("b");
  });

  it("adds a new named case", () => {
    const handlers = renderControl();
    fireEvent.click(screen.getByRole("button", { name: "+ Add case" }));
    fireEvent.change(screen.getByPlaceholderText("case name (e.g. SLAB)"), { target: { value: "BLANK" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(handlers.onAdd).toHaveBeenCalledWith("BLANK");
  });

  it("renames the selected case", () => {
    const handlers = renderControl();
    fireEvent.change(screen.getByRole("textbox", { name: "Case name" }), { target: { value: "WT2" } });
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    expect(handlers.onRename).toHaveBeenCalledWith("b", "WT2");
  });
});
