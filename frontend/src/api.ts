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

function savedRunData(id: string): DemoRunData {
  const value = saved.run_data[id];
  if (!value) throw new ApiError("Saved demonstration run not found", 404);
  return value;
}

type DemoReplayDecision = "approved" | "rejected" | "cancelled";

type DemoReplay = {
  id: string;
  scenarioId: string;
  templateRunId: string;
  idempotencyKey: string;
  createdAtMs: number;
  approvedAtMs?: number;
  decision?: DemoReplayDecision;
  actor?: string;
};

const replayStorageKey = "incidentlab.demo-replays.v1";
const demoReplays = new Map<string, DemoReplay>();

function restoreDemoReplays() {
  if (typeof sessionStorage === "undefined" || import.meta.env.MODE === "test") return;
  try {
    const values = JSON.parse(sessionStorage.getItem(replayStorageKey) ?? "[]") as DemoReplay[];
    for (const value of values) demoReplays.set(value.id, value);
  } catch {
    sessionStorage.removeItem(replayStorageKey);
  }
}

function persistDemoReplays() {
  if (typeof sessionStorage === "undefined" || import.meta.env.MODE === "test") return;
  sessionStorage.setItem(replayStorageKey, JSON.stringify([...demoReplays.values()]));
}

restoreDemoReplays();

export function isDemoReplayRun(id: string) {
  return demoReplays.has(id);
}

function replayState(replay: DemoReplay, now = Date.now()): RunState {
  if (replay.decision === "rejected") return "CLOSED";
  if (replay.decision === "cancelled") return "CANCELLED";
  if (replay.decision !== "approved" || replay.approvedAtMs === undefined) {
    const elapsed = now - replay.createdAtMs;
    if (elapsed < 800) return "CREATED";
    if (elapsed < 2_800) return "REPRODUCING";
    if (elapsed < 5_000) return "COLLECTING";
    if (elapsed < 7_200) return "DIAGNOSING";
    return "AWAITING_REPAIR_APPROVAL";
  }
  const elapsed = now - replay.approvedAtMs;
  if (elapsed < 2_000) return "GENERATING";
  if (elapsed < 6_500) return "VERIFYING";
  if (elapsed < 8_000) return "REPORTING";
  return "COMPLETED";
}

function replayRun(replay: DemoReplay): IncidentRun {
  const template = saved.runs.find((run) => run.id === replay.templateRunId);
  if (!template) throw new ApiError("Saved replay template not found", 500);
  const state = replayState(replay);
  return {
    ...template,
    id: replay.id,
    workflow_id: `incidentlab-demo-${replay.id}`,
    state,
    created_at: new Date(replay.createdAtMs).toISOString(),
    updated_at: new Date().toISOString(),
  };
}

function replayFor(id: string) {
  const replay = demoReplays.get(id);
  if (!replay) throw new ApiError("Saved demonstration run not found", 404);
  return replay;
}

function replayData(replay: DemoReplay): DemoRunData {
  const template = savedRunData(replay.templateRunId);
  const state = replayState(replay);
  const evidenceVisible = !["CREATED", "REPRODUCING", "COLLECTING"].includes(state);
  const diagnosisVisible = !["CREATED", "REPRODUCING", "COLLECTING", "DIAGNOSING"].includes(state);
  const candidateVisible = ["VERIFYING", "REPORTING", "COMPLETED"].includes(state);
  const verificationVisible = ["REPORTING", "COMPLETED"].includes(state);
  const eventCount: Partial<Record<RunState, number>> = {
    CREATED: 1,
    REPRODUCING: 1,
    COLLECTING: 2,
    DIAGNOSING: 2,
    AWAITING_REPAIR_APPROVAL: 3,
    GENERATING: 4,
    VERIFYING: 5,
    REPORTING: 6,
    COMPLETED: template.events.length,
    CLOSED: 4,
    CANCELLED: 3,
  };
  const sourceStart = new Date(template.events[0]?.created_at ?? replay.createdAtMs).getTime();
  const events = template.events.slice(0, eventCount[state] ?? 0).map((event, index) => ({
    ...event,
    id: `${replay.id}-event-${index + 1}`,
    run_id: replay.id,
    actor: index === 3 && replay.actor ? replay.actor : event.actor,
    correlation_id: `demo-${replay.id.slice(0, 8)}-${index + 1}`,
    created_at: new Date(replay.createdAtMs + Math.max(0, new Date(event.created_at).getTime() - sourceStart)).toISOString(),
    details:
      index === 3 && replay.decision
        ? { ...event.details, decision: replay.decision }
        : event.details,
  }));
  if (state === "CANCELLED") {
    events.push({
      id: `${replay.id}-event-cancelled`,
      run_id: replay.id,
      kind: "workflow_cancelled",
      actor: replay.actor ?? "demo-reviewer",
      correlation_id: `demo-${replay.id.slice(0, 8)}-cancelled`,
      created_at: new Date().toISOString(),
      details: { stage: "investigation", reason: "cancelled during guided replay" },
    });
  }
  return {
    evidence: evidenceVisible ? template.evidence.map((item) => ({ ...item, run_id: replay.id })) : [],
    hypotheses: diagnosisVisible ? template.hypotheses.map((item) => ({ ...item, run_id: replay.id })) : [],
    candidates: candidateVisible ? template.candidates.map((item) => ({ ...item, run_id: replay.id })) : [],
    verifications: verificationVisible ? template.verifications : [],
    events,
    model_usage: diagnosisVisible
      ? template.model_usage.slice(0, candidateVisible ? template.model_usage.length : 1).map((item) => ({ ...item, run_id: replay.id }))
      : [],
    artifacts: template.artifacts,
    report_markdown: `# IncidentLab guided replay: ${replay.scenarioId}\n\n- State: **${state}**\n- Data source: curated saved investigation\n\nThis browser-only run replays the evidence, diagnosis, repair, and verification facts from a saved IncidentLab investigation. It makes no backend or model request.\n`,
  };
}

function demoRunData(id: string): DemoRunData {
  return demoReplays.has(id) ? replayData(replayFor(id)) : savedRunData(id);
}

function readOnly(): never {
  throw new ApiError("This deployment is a read-only demonstration", 405);
}

export const demoApi: IncidentLabClient = {
  scenarios: async () => saved.scenarios,
  runs: async (state) => [...demoReplays.values()].map(replayRun).concat(saved.runs).filter((run) => !state || run.state === state),
  run: async (id) => {
    const run = demoReplays.has(id) ? replayRun(replayFor(id)) : saved.runs.find((item) => item.id === id);
    if (!run) throw new ApiError("Saved demonstration run not found", 404);
    return run;
  },
  evidence: async (id) => demoRunData(id).evidence,
  hypotheses: async (id) => demoRunData(id).hypotheses,
  candidates: async (id) => demoRunData(id).candidates,
  verifications: async (id) => demoRunData(id).verifications,
  events: async (id) => demoRunData(id).events,
  modelUsage: async (id) => demoRunData(id).model_usage,
  createRun: async (scenarioId, idempotencyKey) => {
    const existing = [...demoReplays.values()].find((item) => item.idempotencyKey === idempotencyKey);
    if (existing) return replayRun(existing);
    const template = saved.runs.find((run) => run.scenario_id === scenarioId && run.state === "COMPLETED");
    if (!template) throw new ApiError("No saved replay is available for this scenario", 404);
    const replay: DemoReplay = {
      id: crypto.randomUUID(),
      scenarioId,
      templateRunId: template.id,
      idempotencyKey,
      createdAtMs: Date.now(),
    };
    demoReplays.set(replay.id, replay);
    persistDemoReplays();
    return replayRun(replay);
  },
  approve: async (id, actor, decision) => {
    const replay = demoReplays.get(id);
    if (!replay) return readOnly();
    replay.actor = actor;
    replay.decision = decision;
    if (decision === "approved") replay.approvedAtMs = Date.now();
    persistDemoReplays();
    return { run_id: id, decision };
  },
  cancel: async (id, actor) => {
    const replay = demoReplays.get(id);
    if (!replay) return readOnly();
    replay.actor = actor;
    replay.decision = "cancelled";
    persistDemoReplays();
    return { run_id: id, cancel_requested: true };
  },
  artifactText: async (ref) => {
    for (const data of Object.values(saved.run_data)) {
      const value = data.artifacts[ref];
      if (value !== undefined) return value;
    }
    throw new ApiError("Saved artifact not found", 404);
  },
  reportUrl: (id, format) => {
    const data = demoRunData(id);
    const run = demoReplays.has(id) ? replayRun(replayFor(id)) : saved.runs.find((item) => item.id === id);
    const content =
      format === "markdown"
        ? data.report_markdown
        : JSON.stringify(
            {
              report_version: "incident-report-v1",
              run,
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
