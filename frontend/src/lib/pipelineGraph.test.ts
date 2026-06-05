import { describe, expect, it } from "vitest";

import type { PipelineSummary } from "@/types";

import { buildPipelineGraph, layoutGraph } from "./pipelineGraph";

// Mirrors .bio_pipeline/yamls/growth_rates_pipeline.yaml (growth_rate_fit_pipeline),
// trimmed to the steps that exercise fan-in, a merge, and a no-edge parameter.
const pipeline: PipelineSummary = {
  name: "growth_rate_fit_pipeline",
  inputs: ["raw_data", "meta_data"],
  processes: [
    {
      name: "df_parsed",
      package: "labUtils.media_bot",
      method: "parse",
      parameters: { raw_data: "raw_data", meta_data: "meta_data", value_column_name: "od600" },
    },
    {
      name: "df_transformed",
      package: "labUtils.growth_rates",
      method: "transform_to_log_n_n0",
      parameters: { df: "df_parsed", value_col: "od600" },
    },
    {
      name: "df_fit_modified_gompertz",
      package: "labUtils.growth_rates",
      method: "fit_modified_gompertz_per_series",
      parameters: { df: "df_transformed" },
    },
    {
      name: "df_fit_max_growth_rate",
      package: "labUtils.growth_rates",
      method: "fit_max_growth_rate_per_series",
      parameters: { df: "df_transformed" },
    },
    {
      name: "df_combined_fit",
      package: "labUtils.utils",
      method: "smart_join_drop_right",
      parameters: { left_df: "df_fit_max_growth_rate", right_df: "df_fit_modified_gompertz" },
    },
  ],
  outputs: ["df_parsed", "df_combined_fit"],
};

function incoming(edges: { source: string; target: string; label?: unknown }[], target: string) {
  return edges.filter((edge) => edge.target === target);
}

describe("buildPipelineGraph", () => {
  it("creates one node per input, process, and output with prefixed ids", () => {
    const { nodes } = buildPipelineGraph(pipeline);
    expect(nodes).toHaveLength(2 + 5 + 2);
    expect(nodes.find((node) => node.id === "input:raw_data")?.data.kind).toBe("input");
    expect(nodes.find((node) => node.id === "proc:df_parsed")?.data.kind).toBe("process");
    expect(nodes.find((node) => node.id === "output:df_parsed")?.data.kind).toBe("output");
  });

  it("fans both inputs into df_parsed with the parameter key as the edge label", () => {
    const { edges } = buildPipelineGraph(pipeline);
    const into = incoming(edges, "proc:df_parsed");
    expect(into).toHaveLength(2);
    expect(into.map((edge) => `${edge.source}#${edge.label}`).sort()).toEqual([
      "input:meta_data#meta_data",
      "input:raw_data#raw_data",
    ]);
  });

  it("captures the merge: df_combined_fit has two incoming edges (left_df, right_df)", () => {
    const { edges } = buildPipelineGraph(pipeline);
    const into = incoming(edges, "proc:df_combined_fit");
    expect(into).toHaveLength(2);
    expect(into.map((edge) => edge.label).sort()).toEqual(["left_df", "right_df"]);
  });

  it("ignores parameters whose key does not suggest a payload", () => {
    const { edges } = buildPipelineGraph(pipeline);
    // value_column_name / value_col are plain params, not payload references.
    expect(edges.some((edge) => edge.label === "value_column_name")).toBe(false);
    expect(edges.some((edge) => edge.label === "value_col")).toBe(false);
  });

  it("links each output back to its producing payload", () => {
    const { edges } = buildPipelineGraph(pipeline);
    expect(edges).toContainEqual(
      expect.objectContaining({ source: "proc:df_parsed", target: "output:df_parsed" }),
    );
    expect(edges).toContainEqual(
      expect.objectContaining({ source: "proc:df_combined_fit", target: "output:df_combined_fit" }),
    );
  });

  it("does not create an edge for a reference to an unknown payload", () => {
    const broken: PipelineSummary = {
      name: "broken",
      inputs: [],
      processes: [
        {
          name: "step",
          package: "p",
          method: "m",
          parameters: { df: "missing" },
        },
      ],
      outputs: [],
    };
    expect(buildPipelineGraph(broken).edges).toHaveLength(0);
  });
});

describe("layoutGraph", () => {
  it("assigns finite positions and left/right handles to every node", () => {
    const { nodes, edges } = buildPipelineGraph(pipeline);
    const laid = layoutGraph(nodes, edges);
    expect(laid).toHaveLength(nodes.length);
    for (const node of laid) {
      expect(Number.isFinite(node.position.x)).toBe(true);
      expect(Number.isFinite(node.position.y)).toBe(true);
      expect(node.sourcePosition).toBe("right");
      expect(node.targetPosition).toBe("left");
    }
  });
});
