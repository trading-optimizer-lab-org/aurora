import { describe, expect, it } from "vitest";
import { demoRunDetail, demoRuns } from "./fixtures";

describe("dashboard contracts", () => {
  it("keeps stable run identity and pagination", () => {
    expect(demoRuns.schema_version).toBe(1);
    expect(demoRuns.items[0].run_id).toBeGreaterThan(0);
    expect(demoRuns.next_cursor).toBeNull();
  });

  it("links detail jobs, artifacts, and results to one run", () => {
    const detail = demoRunDetail;
    expect(detail.run.run_id).toBe(detail.jobs[0].run_id);
    expect(detail.artifacts[0].run_id).toBe(detail.run.run_id);
    expect(detail.results[0].run_id).toBe(detail.run.run_id);
  });
});
