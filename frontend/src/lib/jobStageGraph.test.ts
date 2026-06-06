import { describe, expect, it } from "vitest";

import { buildStageGraph } from "./jobStageGraph";
import type { MaterializedTask } from "@/types";

function task(stage: string, needs: string[], extra: Partial<MaterializedTask> = {}): MaterializedTask {
  return {
    job_name: "j",
    stage,
    matrix_key: {},
    needs,
    pipeline_yaml: "p.yaml",
    pipeline_name: "demo",
    output_dir: "/out",
    input_sources: {},
    process_arg_mapping: {},
    item_index: 0,
    deferred: false,
    ...extra,
  };
}

describe("buildStageGraph", () => {
  it("makes one node per stage with task counts and a needs edge", () => {
    const { nodes, edges } = buildStageGraph([task("prep", []), task("prep", []), task("collate", ["prep"])]);

    expect(nodes.map((node) => node.id)).toEqual(["prep", "collate"]);
    expect(nodes.find((node) => node.id === "prep")?.data.taskCount).toBe(2);
    expect(nodes.find((node) => node.id === "collate")?.data.taskCount).toBe(1);
    expect(edges).toHaveLength(1);
    expect(edges[0]).toMatchObject({ source: "prep", target: "collate" });
  });

  it("marks a stage deferred if any task is deferred and dedupes parallel edges", () => {
    const { nodes, edges } = buildStageGraph([
      task("prep", []),
      task("collate", ["prep"], { deferred: true }),
      task("collate", ["prep"], { deferred: true }),
    ]);

    const collate = nodes.find((node) => node.id === "collate");
    expect(collate?.data.deferred).toBe(true);
    expect(collate?.data.taskCount).toBe(2);
    expect(edges).toHaveLength(1);
  });

  it("ignores a needs reference to an absent stage", () => {
    const { edges } = buildStageGraph([task("only", ["ghost"])]);
    expect(edges).toHaveLength(0);
  });
});
