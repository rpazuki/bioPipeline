import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  emitDraftsToYaml,
  parseYamlToDrafts,
  type PipelineDraft,
} from "./pipelineDraft";

// Vitest runs with cwd = frontend/; the YAML store sits one level up in the repo.
const SAMPLE = readFileSync(
  resolve(process.cwd(), "../.bio_pipeline/yamls/growth_rates_pipeline.yaml"),
  "utf-8",
);

describe("parseYamlToDrafts", () => {
  it("parses both pipelines with full fidelity", () => {
    const { drafts, error } = parseYamlToDrafts(SAMPLE);
    expect(error).toBeUndefined();
    expect(drafts.length).toBeGreaterThanOrEqual(2);
    expect(drafts.map((draft) => draft.name)).toEqual(
      expect.arrayContaining(["growth_rate_fit_pipeline", "growth_rate_replicates_fit_pipeline"]),
    );
  });

  it("coerces the list-form Inputs spec and splits src/package/method from extras", () => {
    const { drafts } = parseYamlToDrafts(SAMPLE);
    const rawData = drafts[0].inputs.find((input) => input.name === "raw_data")!;
    expect(rawData.src).toBe("EMPTY");
    expect(rawData.package).toBe("labUtils.media_bot");
    expect(rawData.method).toBe("parse_raw_CLARIOstar_export");
    expect(rawData.extras).toEqual({ value_column_name: "od600" });
  });

  it("preserves output paths and nested parameter structures", () => {
    const { drafts } = parseYamlToDrafts(SAMPLE);
    const fit = drafts[0];
    expect(fit.outputs).toContainEqual({ name: "df_parsed", path: "parsed_data.csv" });

    const gompertz = fit.processes.find((p) => p.name === "df_fit_modified_gompertz")!;
    expect(gompertz.parameters.fixed_params).toEqual({ y0: 0.0 });
    expect(gompertz.parameters.group_cols).toEqual(["well"]);

    const replicates = drafts[1].processes.find((p) => p.name === "df_replicate_stats")!;
    expect(replicates.parameters.custom_rules).toMatchObject({
      SLAB: { direction: "alphabetical", sample_size: 3 },
    });
  });

  it("returns an error (and no drafts) for non-pipeline YAML without throwing", () => {
    expect(parseYamlToDrafts("just: a mapping").error).toBeDefined();
    expect(parseYamlToDrafts(": : bad").error).toBeDefined();
  });
});

describe("round-trip", () => {
  it("emit(parse(text)) re-parses to the identical drafts (idempotent)", () => {
    const first = parseYamlToDrafts(SAMPLE).drafts;
    const second = parseYamlToDrafts(emitDraftsToYaml(first)).drafts;
    expect(second).toEqual(first);
  });
});

describe("emitDraftsToYaml topological ordering", () => {
  it("orders processes so every payload reference is produced earlier", () => {
    // Deliberately scrambled: a consumer is listed before its producer.
    const draft: PipelineDraft = {
      name: "scrambled",
      inputs: [{ name: "raw", src: "EMPTY", package: "p", method: "m", extras: {} }],
      processes: [
        { name: "b", package: "p", method: "m", parameters: { df: "a" } },
        { name: "a", package: "p", method: "m", parameters: { raw_data: "raw" } },
      ],
      outputs: [{ name: "b", path: "b.csv" }],
    };

    const reparsed = parseYamlToDrafts(emitDraftsToYaml([draft])).drafts[0];
    const order = reparsed.processes.map((process) => process.name);
    expect(order.indexOf("a")).toBeLessThan(order.indexOf("b"));
  });
});
