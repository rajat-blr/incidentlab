import { describe, expect, it, vi } from "vitest";

import { demoApi } from "../api";
import dataset from "./dataset.json";
import evaluation from "../../../docs/results/live-four-scenarios-matched-head-2026-10-09/report.json";

async function sha256(value: string) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

describe("saved demonstration data", () => {
  it("retains every latest live trial, including failed runs and their full audits", () => {
    for (const trial of evaluation.trials) {
      expect(dataset.runs.find((run) => run.id === trial.run_id)).toEqual(trial.report.run);
      const data = dataset.run_data[trial.run_id as keyof typeof dataset.run_data];
      expect(data.events).toEqual(trial.report.events);
      expect(data.model_usage).toEqual(trial.report.model_usage);
      expect(data.verifications).toEqual(trial.report.verifications);
    }
    expect(evaluation.trials.filter((trial) => trial.report.run.state === "FAILED")).toHaveLength(6);
  });

  it("serves a varied investigation history without network access", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const runs = await demoApi.runs();

    expect(runs).toHaveLength(21);
    expect(new Set(runs.map((run) => run.state))).toEqual(
      new Set([
        "COMPLETED",
        "NO_VERIFIED_CANDIDATE",
        "INCONCLUSIVE",
        "FAILED",
        "CLOSED",
        "CANCELLED",
      ]),
    );
    expect(Object.keys(dataset.run_data).sort()).toEqual(runs.map((run) => run.id).sort());
    expect(await demoApi.hypotheses(runs[0]!.id)).toHaveLength(1);
    expect(await demoApi.verifications(runs[0]!.id)).toHaveLength(1);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("runs all four guided scenario replays without network access", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-29T10:00:00Z"));
    const fetch = vi.spyOn(globalThis, "fetch");
    try {
      for (const scenario of ["pool-exhaustion", "inventory-underflow", "upstream-error-masking", "mutation-response-cache"]) {
        const run = await demoApi.createRun(scenario, `guided-${scenario}`);
        expect(run.state).toBe("CREATED");

        vi.advanceTimersByTime(7_500);
        expect((await demoApi.run(run.id)).state).toBe("AWAITING_REPAIR_APPROVAL");
        expect(await demoApi.evidence(run.id)).not.toHaveLength(0);
        expect(await demoApi.hypotheses(run.id)).not.toHaveLength(0);

        await demoApi.approve(run.id, "demo-reviewer", "approved");
        vi.advanceTimersByTime(2_100);
        expect((await demoApi.run(run.id)).state).toBe("VERIFYING");
        expect((await demoApi.candidates(run.id)).length).toBeGreaterThan(0);

        vi.advanceTimersByTime(6_000);
        expect((await demoApi.run(run.id)).state).toBe("COMPLETED");
        expect((await demoApi.verifications(run.id)).length).toBeGreaterThan(0);
      }
      expect(fetch).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps saved historical runs immutable", async () => {
    await expect(
      demoApi.approve("11111111-1111-5111-8111-111111111111", "test", "approved"),
    ).rejects.toEqual(expect.objectContaining({ status: 405 }));
  });

  it("keeps every displayed integrity hash truthful", async () => {
    for (const data of Object.values(dataset.run_data)) {
      const referenced = [...data.evidence, ...data.verifications.flatMap((item) => item.checks)];
      for (const item of referenced) {
        const content = data.artifacts[item.artifact_ref as keyof typeof data.artifacts];
        expect(content, item.artifact_ref).toBeTypeOf("string");
        expect(await sha256(content!), item.artifact_ref).toBe(item.content_sha256);
      }
      for (const candidate of data.candidates) {
        expect(await sha256(candidate.unified_diff), candidate.id).toBe(candidate.diff_sha256);
      }
    }
  });

  it("only cites evidence contained in its saved run", () => {
    for (const data of Object.values(dataset.run_data)) {
      const evidenceIds = new Set(data.evidence.map((item) => item.id));
      for (const hypothesis of data.hypotheses) {
        for (const citation of [
          ...hypothesis.supporting_evidence_ids,
          ...hypothesis.contradicting_evidence_ids,
        ]) {
          expect(evidenceIds.has(citation), citation).toBe(true);
        }
      }
    }
  });
});
