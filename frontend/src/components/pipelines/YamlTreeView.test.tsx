import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import YamlTreeView from "./YamlTreeView";
import type { YamlTreeNode } from "@/types";

const TREE: YamlTreeNode[] = [
  {
    name: "designs",
    path: "designs",
    node_type: "folder",
    pipelines: [],
    is_valid: true,
    error: null,
    children: [
      {
        name: "demo.yaml",
        path: "designs/demo.yaml",
        node_type: "file",
        pipelines: [],
        is_valid: false,
        error: "Missing pipelines",
        children: [],
      },
    ],
  },
];

describe("YamlTreeView", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders nested folders and invalid file markers and forwards selection", async () => {
    const handleSelect = vi.fn();
    const handleNavigate = vi.fn();

    render(<YamlTreeView nodes={TREE} selectedPath="designs/demo.yaml" onSelect={handleSelect} onNavigatePath={handleNavigate} />);

    expect(screen.getAllByText("designs").length).toBeGreaterThan(0);
    expect(screen.getAllByText("demo.yaml").length).toBeGreaterThan(0);
    expect(screen.getByText("invalid")).toBeInTheDocument();

    fireEvent.click(screen.getAllByText("demo.yaml")[1]);
    fireEvent.click(screen.getByRole("button", { name: "root" }));

    expect(handleNavigate).toHaveBeenCalledWith("");

    expect(handleSelect).toHaveBeenCalledWith(expect.objectContaining({ path: "designs/demo.yaml" }));
  });

  it("collapses and re-expands folders", () => {
    render(<YamlTreeView nodes={TREE} selectedPath="" onSelect={vi.fn()} />);

    fireEvent.click(screen.getAllByLabelText("Collapse designs")[0]);
    expect(screen.queryByText("demo.yaml")).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByLabelText("Expand designs")[0]);
    expect(screen.getByText("demo.yaml")).toBeInTheDocument();
  });
});
