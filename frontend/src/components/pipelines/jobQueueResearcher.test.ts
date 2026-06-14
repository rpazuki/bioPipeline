import { describe, expect, it } from "vitest";

import type { Job, PublishedRunSummary } from "@/types";

import { indexRunsByParent, researcherForJob } from "./JobQueuePanel";

function makeRun(overrides: Partial<PublishedRunSummary>): PublishedRunSummary {
  return {
    id: "run-1",
    published_job_id: "pj-1",
    published_version: 1,
    published_job_name: "OD600 ingestion",
    user_id: "u-rp1",
    username: "rp1",
    user_display_name: "Researcher One",
    parent_job_id: "grp-1",
    status: "succeeded",
    total: 3,
    counts: {},
    values: {},
    created_at: "2026-06-14T10:00:00Z",
    ...overrides,
  };
}

function makeJob(overrides: Partial<Job>): Job {
  return {
    id: "job-1",
    status: "succeeded",
    yaml_path: "/x.yaml",
    pipeline_name: "p",
    output_dir: "/out",
    input_sources: {},
    backend: "local",
    log_path: "/log",
    created_at: "2026-06-14T10:00:00Z",
    updated_at: "2026-06-14T10:00:00Z",
    ...overrides,
  };
}

describe("Job Queue researcher attribution", () => {
  it("attributes a child task to the researcher of its parent run", () => {
    const map = indexRunsByParent([makeRun({ parent_job_id: "grp-1" })]);
    const job = makeJob({ id: "child-a", parent_job_id: "grp-1" });

    expect(researcherForJob(job, map)).toBe("Researcher One");
  });

  it("matches the group-parent row by its own id", () => {
    const map = indexRunsByParent([makeRun({ parent_job_id: "grp-1" })]);
    const parentJob = makeJob({ id: "grp-1", parent_job_id: null });

    expect(researcherForJob(parentJob, map)).toBe("Researcher One");
  });

  it("falls back to username, then user_id, when no display name is set", () => {
    const mapNoDisplay = indexRunsByParent([makeRun({ user_display_name: "" })]);
    expect(researcherForJob(makeJob({ parent_job_id: "grp-1" }), mapNoDisplay)).toBe("rp1");

    const mapOnlyId = indexRunsByParent([makeRun({ user_display_name: "", username: "" })]);
    expect(researcherForJob(makeJob({ parent_job_id: "grp-1" }), mapOnlyId)).toBe("u-rp1");
  });

  it("shows an em dash for admin-submitted jobs not tied to any run", () => {
    const map = indexRunsByParent([makeRun({ parent_job_id: "grp-1" })]);

    expect(researcherForJob(makeJob({ id: "adhoc", parent_job_id: null }), map)).toBe("—");
    expect(researcherForJob(makeJob({ id: "adhoc", parent_job_id: "grp-other" }), map)).toBe("—");
  });

  it("keeps separate researchers for distinct parent groups", () => {
    const map = indexRunsByParent([
      makeRun({ id: "r1", parent_job_id: "grp-1", user_display_name: "Alfie" }),
      makeRun({ id: "r2", parent_job_id: "grp-2", user_display_name: "Bo" }),
    ]);

    expect(researcherForJob(makeJob({ parent_job_id: "grp-1" }), map)).toBe("Alfie");
    expect(researcherForJob(makeJob({ parent_job_id: "grp-2" }), map)).toBe("Bo");
  });
});
