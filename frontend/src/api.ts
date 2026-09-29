import demoDataset from "./demo-data/dataset.json";
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

export const isDemoMode = import.meta.env.VITE_DATA_MODE === "demo";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export interface IncidentLabClient {
  scenarios(): Promise<ScenarioSummary[]>;
  runs(state?: RunState): Promise<IncidentRun[]>;
  run(id: string): Promise<IncidentRun>;
  evidence(id: string): Promise<EvidenceItem[]>;
  hypotheses(id: string): Promise<Hypothesis[]>;
  candidates(id: string): Promise<RepairCandidate[]>;
  verifications(id: string): Promise<VerificationRun[]>;
  events(id: string): Promise<AuditEvent[]>;
  modelUsage(id: string): Promise<ModelUsage[]>;
  createRun(scenarioId: string, idempotencyKey: string): Promise<IncidentRun>;
  approve(
    id: string,
    actor: string,
    decision: "approved" | "rejected",
  ): Promise<{ run_id: string; decision: string }>;
  cancel(id: string, actor: string): Promise<{ run_id: string; cancel_requested: boolean }>;
  artifactText(ref: string): Promise<string>;
  reportUrl(id: string, format: "json" | "markdown"): string;
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

export const liveApi: IncidentLabClient = {
  scenarios: () => request<ScenarioSummary[]>("/scenarios"),
  runs: (state) => request<IncidentRun[]>(`/runs${state ? `?state=${state}` : ""}`),
  run: (id) => request<IncidentRun>(`/runs/${id}`),
  evidence: (id) => request<EvidenceItem[]>(`/runs/${id}/evidence`),
  hypotheses: (id) => request<Hypothesis[]>(`/runs/${id}/hypotheses`),
  candidates: (id) => request<RepairCandidate[]>(`/runs/${id}/candidates`),
  verifications: (id) => request<VerificationRun[]>(`/runs/${id}/verifications`),
  events: (id) => request<AuditEvent[]>(`/runs/${id}/events`),
  modelUsage: (id) => request<ModelUsage[]>(`/runs/${id}/model-usage`),
  createRun: (scenarioId, idempotencyKey) =>
    request<IncidentRun>("/runs", {
      method: "POST",
      body: JSON.stringify({
        schema_version: 1,
        scenario_id: scenarioId,
        idempotency_key: idempotencyKey,
      }),
    }),
  approve: (id, actor, decision) =>
    request<{ run_id: string; decision: string }>(`/runs/${id}/repair-approval`, {
      method: "POST",
      body: JSON.stringify({ schema_version: 1, actor, decision }),
    }),
  cancel: (id, actor) =>
    request<{ run_id: string; cancel_requested: boolean }>(`/runs/${id}/cancel`, {
      method: "POST",
      body: JSON.stringify({ schema_version: 1, actor }),
    }),
  artifactText: async (ref) => {
    const response = await fetch(`${API_ROOT}${ref}`);
    if (!response.ok) throw new ApiError(response.statusText, response.status);
    return response.text();
  },
  reportUrl: (id, format) => `${API_ROOT}/runs/${id}/report?format=${format}`,
};

type DemoRunData = {
  evidence: EvidenceItem[];
  hypotheses: Hypothesis[];
  candidates: RepairCandidate[];
  verifications: VerificationRun[];
  events: AuditEvent[];
  model_usage: ModelUsage[];
  artifacts: Record<string, string>;
  report_markdown: string;
};

type DemoDataset = {
  scenarios: ScenarioSummary[];
  runs: IncidentRun[];
  run_data: Record<string, DemoRunData>;
};

const saved = demoDataset as DemoDataset;

function demoRun(id: string): DemoRunData {
  const value = saved.run_data[id];
  if (!value) throw new ApiError("Saved demonstration run not found", 404);
  return value;
}

function readOnly(): never {
  throw new ApiError("This deployment is a read-only demonstration", 405);
}

export const demoApi: IncidentLabClient = {
  scenarios: async () => saved.scenarios,
  runs: async (state) => saved.runs.filter((run) => !state || run.state === state),
  run: async (id) => {
    const run = saved.runs.find((item) => item.id === id);
    if (!run) throw new ApiError("Saved demonstration run not found", 404);
    return run;
  },
  evidence: async (id) => demoRun(id).evidence,
  hypotheses: async (id) => demoRun(id).hypotheses,
  candidates: async (id) => demoRun(id).candidates,
  verifications: async (id) => demoRun(id).verifications,
  events: async (id) => demoRun(id).events,
  modelUsage: async (id) => demoRun(id).model_usage,
  createRun: async () => readOnly(),
  approve: async () => readOnly(),
  cancel: async () => readOnly(),
  artifactText: async (ref) => {
    for (const data of Object.values(saved.run_data)) {
      const value = data.artifacts[ref];
      if (value !== undefined) return value;
    }
    throw new ApiError("Saved artifact not found", 404);
  },
  reportUrl: (id, format) => {
    const data = demoRun(id);
    const content =
      format === "markdown"
        ? data.report_markdown
        : JSON.stringify(
            {
              report_version: "incident-report-v1",
              run: saved.runs.find((run) => run.id === id),
              evidence: data.evidence,
              hypotheses: data.hypotheses,
              candidates: data.candidates,
              verifications: data.verifications,
              events: data.events,
              model_usage: data.model_usage,
            },
            null,
            2,
          );
    const mediaType = format === "markdown" ? "text/markdown" : "application/json";
    return `data:${mediaType};charset=utf-8,${encodeURIComponent(content)}`;
  },
};

export const api: IncidentLabClient = isDemoMode ? demoApi : liveApi;
