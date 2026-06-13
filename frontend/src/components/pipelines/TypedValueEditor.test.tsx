import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import TypedValueEditor from "./TypedValueEditor";
import type { PublishedField, ResolvedType } from "@/types";

afterEach(cleanup);

const SCHEMA: ResolvedType = {
  name: "CustomReplicateRule",
  fields: [
    {
      name: "direction",
      type: "enum",
      container: "single",
      required: false,
      options: [
        { label: "alphabetical", value: "alphabetical" },
        { label: "numerical", value: "numerical" },
      ],
    },
    { name: "sample_size", type: "integer", container: "single", required: false, options: [] },
  ],
};

function Harness({ container }: { container: "single" | "list" | "map" }) {
  const [value, setValue] = useState<unknown>(container === "list" ? [] : {});
  const field = {
    id: "f",
    label: "Rules",
    type: "typed",
    required: true,
    help: "",
    example: "",
    options: [],
    container,
    type_schema: SCHEMA,
  } as PublishedField;
  return (
    <>
      <TypedValueEditor field={field} value={value} onChange={setValue} />
      <pre data-testid="out">{JSON.stringify(value)}</pre>
    </>
  );
}

const out = () => JSON.parse(screen.getByTestId("out").textContent || "null");

describe("TypedValueEditor", () => {
  it("single: edits leaf fields into an object", () => {
    render(<Harness container="single" />);
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "3" } });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "alphabetical" } });
    expect(out()).toEqual({ sample_size: "3", direction: "alphabetical" });
  });

  it("map: adds a keyed entry of the type", () => {
    render(<Harness container="map" />);
    fireEvent.click(screen.getByText("+ Add entry"));
    fireEvent.change(screen.getByPlaceholderText("key (e.g. SLAB)"), { target: { value: "SLAB" } });
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "2" } });
    expect(out()).toEqual({ SLAB: { sample_size: "2" } });
  });

  it("list: adds an ordered item of the type", () => {
    render(<Harness container="list" />);
    fireEvent.click(screen.getByText("+ Add CustomReplicateRule"));
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "5" } });
    expect(out()).toEqual([{ sample_size: "5" }]);
  });

  it("map: drops blank-keyed rows from the produced object", () => {
    render(<Harness container="map" />);
    fireEvent.click(screen.getByText("+ Add entry"));
    // A freshly added row with no key contributes nothing until a key is typed.
    expect(out()).toEqual({});
  });
});
