export type RunState =
  | "CREATED"
  | "REPRODUCING"
  | "COLLECTING"
  | "DIAGNOSING"
  | "AWAITING_REPAIR_APPROVAL"
  | "GENERATING"
  | "VERIFYING"
  | "REPORTING"
  | "COMPLETED"
  | "NO_VERIFIED_CANDIDATE"
  | "INCONCLUSIVE"
  | "CLOSED"
  | "FAILED"
  | "CANCELLED";

export interface IncidentRun {
  schema_version: 1;
  id: string;
  scenario_id: string;
  scenario_version: number;
  pinned_commit: string;
  workflow_id: string;
  state: RunState;
  created_at: string;
  updated_at: string;
}

export interface ScenarioSummary {
  schema_version: 1;
  id: string;
  version: number;
  service: string;
  description: string;
}

export interface EvidenceItem {
  schema_version: 1;
  id: string;
  run_id: string;
  kind: "metric" | "trace" | "log" | "commit" | "source" | "gap";
  source: string;
  retrieval_method: string;
  observed_start: string;
  observed_end: string;
  service: string;
  summary: string;
  artifact_ref: string;
  content_sha256: string;
}

export interface EvidenceLookup {
  schema_version: 1;
  tool: string;
  evidence_id: string;
}

export interface Hypothesis {
  schema_version: 1;
  id: string;
  run_id: string;
  summary: string;
  mechanism: string;
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  confidence: "low" | "medium" | "high";
  proposed_checks: EvidenceLookup[];
  model_id: string | null;
  prompt_version: string | null;
}

export interface RepairCandidate {
  schema_version: 1;
  id: string;
  run_id: string;
  target_commit: string;
  unified_diff: string;
  explanation: string;
  expected_behavior: string;
  changed_paths: string[];
  generator_id: string;
  diff_sha256: string;
  policy_status: "accepted";
  policy_version: string;
}

export interface VerificationCheck {
  schema_version: 1;
  name: string;
  outcome: "PASS" | "FAIL" | "INCONCLUSIVE";
  started_at: string;
  finished_at: string;
  exit_code: number | null;
  failure_reason: string | null;
  artifact_ref: string;
  content_sha256: string;
}

export interface VerificationRun {
  schema_version: 1;
  id: string;
  candidate_id: string;
  environment_digest: string;
  checks: VerificationCheck[];
  outcome: "PASS" | "FAIL" | "INCONCLUSIVE";
  score_version: string;
  rank: number | null;
  score: Record<string, number> | null;
  started_at: string;
  finished_at: string;
}

export interface AuditEvent {
  id: string;
  run_id: string;
  kind: string;
  actor: string;
  correlation_id: string;
  created_at: string;
  details: Record<string, unknown>;
}

export interface ModelUsage {
  schema_version: 1;
  id: string;
  run_id: string;
  provider: string;
  model_id: string;
  prompt_version: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  estimated_cost_usd: number;
}

export const terminalStates = new Set<RunState>([
  "COMPLETED",
  "NO_VERIFIED_CANDIDATE",
  "INCONCLUSIVE",
  "CLOSED",
  "FAILED",
  "CANCELLED",
]);
