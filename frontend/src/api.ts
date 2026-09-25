import type {
  AuditEvent,
  EvidenceItem,
  Hypothesis,
  IncidentRun,
  ModelUsage,
  RepairCandidate,
  RunState,
  ScenarioSummary,
  VerificationRun,
} from "./types";

const API_ROOT = "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // Preserve the HTTP status text when an error body is not JSON.
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  scenarios: () => request<ScenarioSummary[]>("/scenarios"),
  runs: (state?: RunState) =>
    request<IncidentRun[]>(`/runs${state ? `?state=${state}` : ""}`),
  run: (id: string) => request<IncidentRun>(`/runs/${id}`),
  evidence: (id: string) => request<EvidenceItem[]>(`/runs/${id}/evidence`),
  hypotheses: (id: string) => request<Hypothesis[]>(`/runs/${id}/hypotheses`),
  candidates: (id: string) => request<RepairCandidate[]>(`/runs/${id}/candidates`),
  verifications: (id: string) =>
    request<VerificationRun[]>(`/runs/${id}/verifications`),
  events: (id: string) => request<AuditEvent[]>(`/runs/${id}/events`),
  modelUsage: (id: string) => request<ModelUsage[]>(`/runs/${id}/model-usage`),
  createRun: (scenarioId: string, idempotencyKey: string) =>
    request<IncidentRun>("/runs", {
      method: "POST",
      body: JSON.stringify({
        schema_version: 1,
        scenario_id: scenarioId,
        idempotency_key: idempotencyKey,
      }),
    }),
  approve: (id: string, actor: string, decision: "approved" | "rejected") =>
    request<{ run_id: string; decision: string }>(`/runs/${id}/repair-approval`, {
      method: "POST",
      body: JSON.stringify({ schema_version: 1, actor, decision }),
    }),
  cancel: (id: string, actor: string) =>
    request<{ run_id: string; cancel_requested: boolean }>(`/runs/${id}/cancel`, {
      method: "POST",
      body: JSON.stringify({ schema_version: 1, actor }),
    }),
  artifactText: async (ref: string) => {
    const response = await fetch(`${API_ROOT}${ref}`);
    if (!response.ok) throw new ApiError(response.statusText, response.status);
    return response.text();
  },
  reportUrl: (id: string, format: "json" | "markdown") =>
    `${API_ROOT}/runs/${id}/report?format=${format}`,
};
