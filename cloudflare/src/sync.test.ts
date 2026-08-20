import { describe, expect, it } from "vitest";
import { buildScheduledBatch } from "./sync";

describe("scheduled GitHub sync", () => {
  it("normalizes recent runs without inventing job or artifact rows", () => {
    const batch = buildScheduledBatch({
      workflow_runs: [{
        id: 123,
        workflow_id: 456,
        name: "SP500 Atlas Static Run",
        display_title: "Atlas run",
        status: "in_progress",
        conclusion: null,
        event: "schedule",
        head_branch: "main",
        head_sha: "abc",
        actor: { login: "tester" },
        run_number: 7,
        run_attempt: 1,
        created_at: "2026-08-20T12:00:00Z",
        updated_at: "2026-08-20T12:01:00Z",
        run_started_at: "2026-08-20T12:00:05Z",
        html_url: "https://github.com/example/run/123",
      }],
    }, "2026-08-20T12:02:00Z");

    expect(batch.runs).toHaveLength(1);
    expect(batch.runs[0]).toMatchObject({
      run_id: 123,
      workflow_id: 456,
      workflow_name: "SP500 Atlas Static Run",
      status: "in_progress",
      parser_status: "specialized",
    });
    expect(batch.jobs).toEqual([]);
    expect(batch.artifacts).toEqual([]);
    expect(batch.results).toEqual([]);
    expect(batch.archives).toEqual([]);
  });
});
