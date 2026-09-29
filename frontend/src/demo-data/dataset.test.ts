import { describe, expect, it, vi } from "vitest";

import { demoApi } from "../api";
import dataset from "./dataset.json";

async function sha256(value: string) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

describe("saved demonstration data", () => {
  it("serves complete runs without network access", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const runs = await demoApi.runs();

    expect(runs).toHaveLength(2);
    expect(runs.every((run) => run.state === "COMPLETED")).toBe(true);
    expect(await demoApi.hypotheses(runs[0]!.id)).toHaveLength(1);
    expect(await demoApi.verifications(runs[0]!.id)).toHaveLength(1);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("fails closed for mutation attempts", async () => {
    await expect(demoApi.createRun("pool-exhaustion", "test")).rejects.toEqual(
      expect.objectContaining({ status: 405 }),
    );
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
