import {
  Activity,
  AlertTriangle,
  Check,
  ChevronRight,
  CircleDot,
  Clock3,
  Code2,
  Database,
  Download,
  FileCode2,
  FileText,
  Gauge,
  GitCommitHorizontal,
  ListChecks,
  LoaderCircle,
  OctagonX,
  Play,
  RefreshCw,
  Route,
  ScrollText,
  Search,
  ShieldCheck,
  Square,
  TerminalSquare,
  X,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";
import {
  Link,
  Navigate,
  Route as RouterRoute,
  Routes,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

import { api, ApiError } from "./api";
import type {
  AuditEvent,
  EvidenceItem,
  IncidentRun,
  ModelUsage,
  RepairCandidate,
  RunState,
  VerificationCheck,
  VerificationRun,
} from "./types";
import { terminalStates } from "./types";

const stages: { label: string; state: RunState }[] = [
  { label: "Reproduce", state: "REPRODUCING" },
  { label: "Collect", state: "COLLECTING" },
  { label: "Diagnose", state: "DIAGNOSING" },
  { label: "Approval", state: "AWAITING_REPAIR_APPROVAL" },
  { label: "Generate", state: "GENERATING" },
  { label: "Verify", state: "VERIFYING" },
  { label: "Report", state: "REPORTING" },
];

const stateLabels: Record<RunState, string> = {
  CREATED: "Created",
  REPRODUCING: "Reproducing",
  COLLECTING: "Collecting evidence",
  DIAGNOSING: "Diagnosing",
  AWAITING_REPAIR_APPROVAL: "Awaiting approval",
  GENERATING: "Generating repair",
  VERIFYING: "Verifying",
  REPORTING: "Building report",
  COMPLETED: "Completed",
  NO_VERIFIED_CANDIDATE: "No verified candidate",
  INCONCLUSIVE: "Inconclusive",
  CLOSED: "Closed",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

function statusTone(state: RunState | string) {
  if (state === "COMPLETED" || state === "PASS" || state === "accepted") return "success";
  if (state === "FAILED" || state === "FAIL" || state === "NO_VERIFIED_CANDIDATE") {
    return "danger";
  }
  if (state === "INCONCLUSIVE" || state === "AWAITING_REPAIR_APPROVAL") return "warning";
  if (state === "CANCELLED" || state === "CLOSED") return "neutral";
  return "active";
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function shortId(value: string, length = 8) {
  return value.slice(0, length);
}

function humanize(value: string) {
  return value
    .toLowerCase()
    .replaceAll(/[_-]/g, " ")
    .replace(/^./, (letter) => letter.toUpperCase());
}

function StatusBadge({ value, label }: { value: string; label?: string }) {
  return (
    <span className={`status-badge status-${statusTone(value)}`}>
      <span className="status-dot" />
      {label ?? humanize(value)}
    </span>
  );
}

function EmptyState({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return (
    <div className="empty-state">
      <span className="empty-icon">{icon}</span>
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}

function ErrorState({ error }: { error: unknown }) {
  const detail = error instanceof ApiError ? error.message : "The request could not be completed.";
  return (
    <div className="notice notice-danger" role="alert">
      <AlertTriangle size={17} />
      <div>
        <strong>Unable to load this view</strong>
        <span>{detail}</span>
      </div>
    </div>
  );
}

function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <Link className="brand" to="/runs">
          <span className="brand-mark">I</span>
          <span>IncidentLab</span>
        </Link>
        <nav className="primary-nav" aria-label="Primary navigation">
          <Link className="nav-link active" to="/runs">
            Runs
          </Link>
        </nav>
        <div className="environment-label">
          <span className="system-dot" /> Local development
        </div>
      </header>
      <main className="main-shell">{children}</main>
    </div>
  );
}

function RunsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<"ALL" | RunState>("ALL");
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [scenario, setScenario] = useState("");

  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api.runs(),
    refetchInterval: (query) =>
      query.state.data?.some((run) => !terminalStates.has(run.state)) ? 2_000 : false,
  });
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
  const createRun = useMutation({
    mutationFn: () => {
      const selected = scenario || scenarios.data?.[0]?.id;
      if (!selected) throw new Error("Select a scenario");
      return api.createRun(selected, `web-${crypto.randomUUID()}`);
    },
    onSuccess: async (run) => {
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      navigate(`/runs/${run.id}`);
    },
  });
  const allRuns = runs.data ?? [];
  const visible = allRuns.filter((run) => {
    const value = search.toLowerCase();
    const matchesText = run.id.toLowerCase().includes(value) || run.scenario_id.toLowerCase().includes(value);
    return matchesText && (filter === "ALL" || run.state === filter);
  }).sort((left, right) => {
    const priority = (state: RunState) => state === "AWAITING_REPAIR_APPROVAL" ? 0 : terminalStates.has(state) ? 2 : 1;
    return priority(left.state) - priority(right.state) || new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime();
  });
  const needsReview = allRuns.filter((run) => run.state === "AWAITING_REPAIR_APPROVAL").length;
  const running = allRuns.filter((run) => !terminalStates.has(run.state) && run.state !== "AWAITING_REPAIR_APPROVAL").length;
  const completed = allRuns.filter((run) => run.state === "COMPLETED").length;
  const unsuccessful = allRuns.filter((run) => ["FAILED", "NO_VERIFIED_CANDIDATE", "INCONCLUSIVE"].includes(run.state)).length;

  function submit(event: FormEvent) {
    event.preventDefault();
    createRun.mutate();
  }

  return (
    <AppShell>
      <header className="topbar">
        <div>
          <h1>Incident runs</h1>
          <p>Investigations, repair decisions, and verification outcomes.</p>
        </div>
        <button className="button button-primary" type="button" onClick={() => setShowCreate(true)}>
          <Play size={16} /> Start investigation
        </button>
      </header>
      <div className="page-content">
        <section className="queue-summary" aria-label="Run summary">
          <button type="button" className={filter === "AWAITING_REPAIR_APPROVAL" ? "queue-stat active" : "queue-stat"} onClick={() => setFilter((current) => current === "AWAITING_REPAIR_APPROVAL" ? "ALL" : "AWAITING_REPAIR_APPROVAL")}><strong>{needsReview}</strong><span>Needs review</span></button>
          <div className="queue-stat"><strong>{running}</strong><span>In progress</span></div>
          <button type="button" className={filter === "COMPLETED" ? "queue-stat active" : "queue-stat"} onClick={() => setFilter((current) => current === "COMPLETED" ? "ALL" : "COMPLETED")}><strong>{completed}</strong><span>Completed</span></button>
          <div className="queue-stat"><strong>{unsuccessful}</strong><span>Needs attention</span></div>
        </section>
        <section className="toolbar" aria-label="Run filters">
          <label className="search-field">
            <Search size={16} />
            <span className="sr-only">Search runs</span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by scenario or run ID"
            />
          </label>
          <label className="select-field">
            <span>State</span>
            <select value={filter} onChange={(event) => setFilter(event.target.value as "ALL" | RunState)}>
              <option value="ALL">All states</option>
              {Object.entries(stateLabels).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <button className="icon-button" type="button" aria-label="Refresh runs" onClick={() => runs.refetch()}>
            <RefreshCw size={16} />
          </button>
        </section>

        {runs.isLoading ? <PageLoader label="Loading incident runs" /> : null}
        {runs.error ? <ErrorState error={runs.error} /> : null}
        {!runs.isLoading && !runs.error && visible.length === 0 ? (
          <EmptyState
            icon={<Activity size={24} />}
            title="No incident runs found"
            detail="Start an investigation to reproduce the fixture and collect attributable evidence."
          />
        ) : null}
        {visible.length ? (
          <div className="table-wrap">
            <table className="runs-table">
              <thead><tr><th>Investigation</th><th>Status</th><th>Progress</th><th>Pinned commit</th><th>Updated</th><th><span className="sr-only">Open</span></th></tr></thead>
              <tbody>
                {visible.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <Link className="run-name" to={`/runs/${run.id}`}>{humanize(run.scenario_id)}</Link>
                      <span className="cell-secondary">{shortId(run.id)} · v{run.scenario_version}</span>
                    </td>
                    <td><StatusBadge value={run.state} label={stateLabels[run.state]} /></td>
                    <td><RunProgress state={run.state} /></td>
                    <td><code>{shortId(run.pinned_commit)}</code></td>
                    <td>{formatDate(run.updated_at)}</td>
                    <td><Link className="row-link" to={`/runs/${run.id}`} aria-label={`Open run ${run.id}`}><ChevronRight size={18} /></Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>

      {showCreate ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setShowCreate(false)}>
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="create-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <div><span className="eyebrow">New run</span><h2 id="create-title">Start an investigation</h2></div>
              <button className="icon-button" type="button" aria-label="Close" onClick={() => setShowCreate(false)}><X size={18} /></button>
            </div>
            <form onSubmit={submit}>
              <label className="form-field">
                <span>Scenario</span>
                <select value={scenario} onChange={(event) => setScenario(event.target.value)} required>
                  <option value="" disabled>Select a scenario</option>
                  {scenarios.data?.map((item) => <option key={item.id} value={item.id}>{humanize(item.id)} · {item.service}</option>)}
                </select>
              </label>
              {scenario ? <p className="scenario-description">{scenarios.data?.find((item) => item.id === scenario)?.description}</p> : null}
              {createRun.error ? <ErrorState error={createRun.error} /> : null}
              <div className="modal-actions">
                <button className="button" type="button" onClick={() => setShowCreate(false)}>Cancel</button>
                <button className="button button-primary" disabled={createRun.isPending || !scenario} type="submit">
                  {createRun.isPending ? <LoaderCircle className="spin" size={16} /> : <Play size={16} />}
                  Start run
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}
    </AppShell>
  );
}

function RunProgress({ state }: { state: RunState }) {
  const index = stages.findIndex((stage) => stage.state === state);
  const completedWorkflow = state === "COMPLETED" || state === "NO_VERIFIED_CANDIDATE" || state === "INCONCLUSIVE" || state === "CLOSED";
  const done = completedWorkflow ? stages.length : index >= 0 ? index : 0;
  return <div className="run-progress" aria-label={`${done} of ${stages.length} stages complete`}><span><i style={{ width: `${(done / stages.length) * 100}%` }} /></span><small>{done} of {stages.length}</small></div>;
}

function PageLoader({ label }: { label: string }) {
  return <div className="page-loader"><LoaderCircle className="spin" size={20} /> {label}</div>;
}

type TabId = "overview" | "evidence" | "diagnosis" | "repair" | "verification" | "audit";
const tabs: { id: TabId; label: string; icon: ReactNode }[] = [
  { id: "overview", label: "Overview", icon: <Gauge size={16} /> },
  { id: "evidence", label: "Evidence", icon: <Database size={16} /> },
  { id: "diagnosis", label: "Diagnosis", icon: <Search size={16} /> },
  { id: "repair", label: "Repair", icon: <Code2 size={16} /> },
  { id: "verification", label: "Verification", icon: <ListChecks size={16} /> },
  { id: "audit", label: "Audit", icon: <ScrollText size={16} /> },
];

function RunDetailPage() {
  const { runId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (tabs.some((item) => item.id === params.get("tab")) ? params.get("tab") : "overview") as TabId;
  const queryClient = useQueryClient();
  const [actor, setActor] = useState(() => localStorage.getItem("incidentlab.actor") ?? "local-reviewer");
  const [artifact, setArtifact] = useState<{ title: string; ref: string } | null>(null);
  const [approvalDismissed, setApprovalDismissed] = useState(false);

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId),
    refetchInterval: (query) => query.state.data && !terminalStates.has(query.state.data.state) ? 1_500 : false,
  });
  const evidence = useQuery({ queryKey: ["evidence", runId], queryFn: () => api.evidence(runId) });
  const hypotheses = useQuery({ queryKey: ["hypotheses", runId], queryFn: () => api.hypotheses(runId) });
  const candidates = useQuery({ queryKey: ["candidates", runId], queryFn: () => api.candidates(runId), refetchInterval: run.data && !terminalStates.has(run.data.state) ? 2_000 : false });
  const verifications = useQuery({ queryKey: ["verifications", runId], queryFn: () => api.verifications(runId), refetchInterval: run.data?.state === "VERIFYING" ? 2_000 : false });
  const events = useQuery({ queryKey: ["events", runId], queryFn: () => api.events(runId), refetchInterval: run.data && !terminalStates.has(run.data.state) ? 2_000 : false });
  const modelUsage = useQuery({ queryKey: ["model-usage", runId], queryFn: () => api.modelUsage(runId) });

  useEffect(() => {
    if (!run.data) return;
    for (const key of ["evidence", "hypotheses", "candidates", "verifications", "events", "model-usage"]) {
      void queryClient.invalidateQueries({ queryKey: [key, runId] });
    }
  }, [queryClient, run.data?.state, runId]);

  const approval = useMutation({
    mutationFn: (decision: "approved" | "rejected") => api.approve(runId, actor.trim(), decision),
    onSuccess: async () => {
      localStorage.setItem("incidentlab.actor", actor.trim());
      setApprovalDismissed(true);
      await queryClient.invalidateQueries({ queryKey: ["run", runId] });
      await queryClient.invalidateQueries({ queryKey: ["events", runId] });
    },
  });
  const cancel = useMutation({
    mutationFn: () => api.cancel(runId, actor.trim()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["run", runId] }),
  });

  if (run.isLoading) return <AppShell><PageLoader label="Loading run review" /></AppShell>;
  if (run.error || !run.data) return <AppShell><div className="page-content"><ErrorState error={run.error} /></div></AppShell>;

  const active = !terminalStates.has(run.data.state);
  const selectedEvidence = evidence.data ?? [];
  const selectedHypotheses = hypotheses.data ?? [];
  const selectedCandidates = candidates.data ?? [];
  const selectedVerifications = verifications.data ?? [];
  const selectedEvents = events.data ?? [];

  return (
    <AppShell>
      <header className="detail-topbar">
        <div className="detail-title-row">
          <div className="detail-title">
            <div className="breadcrumbs"><Link to="/runs">Runs</Link><ChevronRight size={13} /><span>{humanize(run.data.scenario_id)}</span></div>
            <h1>{humanize(run.data.scenario_id)} <StatusBadge value={run.data.state} label={stateLabels[run.data.state]} /></h1>
            <span className="detail-meta">Run <code>{shortId(run.data.id)}</code> · commit <code>{shortId(run.data.pinned_commit)}</code> · started {formatDate(run.data.created_at)}</span>
          </div>
        </div>
        <div className="detail-actions">
          <a className="button" href={api.reportUrl(runId, "markdown")}><Download size={16} /> Export report</a>
          {active ? <button className="button button-danger" type="button" disabled={cancel.isPending || !actor.trim()} onClick={() => cancel.mutate()}><Square size={14} /> Cancel</button> : null}
        </div>
      </header>
      <div className="detail-body">
        <WorkflowTimeline run={run.data} />
        <nav className="tab-list" aria-label="Run review sections">
          {tabs.map((item) => (
            <button key={item.id} className={tab === item.id ? "tab active" : "tab"} type="button" onClick={() => setParams({ tab: item.id })}>
              {item.icon}{item.label}
              {item.id === "evidence" && selectedEvidence.length ? <span>{selectedEvidence.length}</span> : null}
              {item.id === "repair" && selectedCandidates.length ? <span>{selectedCandidates.length}</span> : null}
            </button>
          ))}
        </nav>

        <div className="tab-panel">
          {tab === "overview" ? <OverviewTab run={run.data} evidence={selectedEvidence} candidates={selectedCandidates} verifications={selectedVerifications} hypothesis={selectedHypotheses[0]} events={selectedEvents} modelUsage={modelUsage.data ?? []} onOpenApproval={() => setApprovalDismissed(false)} /> : null}
          {tab === "evidence" ? <EvidenceTab items={selectedEvidence} onArtifact={(item) => setArtifact({ title: `${humanize(item.kind)} evidence`, ref: item.artifact_ref })} /> : null}
          {tab === "diagnosis" ? <DiagnosisTab hypotheses={selectedHypotheses} evidence={selectedEvidence} /> : null}
          {tab === "repair" ? <RepairTab candidates={selectedCandidates} events={selectedEvents} /> : null}
          {tab === "verification" ? <VerificationTab run={run.data} candidates={selectedCandidates} verifications={selectedVerifications} onArtifact={(check) => setArtifact({ title: `${humanize(check.name)} log`, ref: check.artifact_ref })} /> : null}
          {tab === "audit" ? <AuditTab events={selectedEvents} /> : null}
        </div>
      </div>
      {artifact ? <ArtifactModal title={artifact.title} artifactRef={artifact.ref} onClose={() => setArtifact(null)} /> : null}
      {run.data.state === "AWAITING_REPAIR_APPROVAL" && !approvalDismissed ? (
        <ApprovalModal
          actor={actor}
          setActor={setActor}
          approval={approval}
          onClose={() => setApprovalDismissed(true)}
        />
      ) : null}
    </AppShell>
  );
}

function WorkflowTimeline({ run }: { run: IncidentRun }) {
  const activeIndex = stages.findIndex((stage) => stage.state === run.state);
  const finished = ["COMPLETED", "NO_VERIFIED_CANDIDATE", "INCONCLUSIVE", "CLOSED"].includes(run.state);
  const successful = run.state === "COMPLETED";
  return (
    <section className={`workflow-timeline${successful ? " successful" : ""}`} aria-label="Workflow progress">
      {stages.map((stage, index) => {
        const complete = finished || activeIndex > index;
        const current = activeIndex === index;
        return (
          <div className={`workflow-stage${complete ? " complete" : ""}${current ? " current" : ""}`} key={stage.state}>
            <span className="stage-marker">{complete ? <Check size={12} /> : current ? <CircleDot size={12} /> : index + 1}</span>
            <span>{stage.label}</span>
          </div>
        );
      })}
    </section>
  );
}

function OverviewTab({ run, evidence, candidates, verifications, hypothesis, events, modelUsage, onOpenApproval }: {
  run: IncidentRun;
  evidence: EvidenceItem[];
  candidates: RepairCandidate[];
  verifications: VerificationRun[];
  hypothesis: { summary: string; mechanism: string; confidence: string } | undefined;
  events: AuditEvent[];
  modelUsage: ModelUsage[];
  onOpenApproval: () => void;
}) {
  const reproduction = events.find((event) => event.kind === "reproduction_recorded");
  const top = [...verifications].sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999))[0];
  const inputTokens = modelUsage.reduce((total, item) => total + item.input_tokens, 0);
  const outputTokens = modelUsage.reduce((total, item) => total + item.output_tokens, 0);
  const estimatedCost = modelUsage.reduce((total, item) => total + Number(item.estimated_cost_usd), 0);
  return (
    <div className="overview-grid">
      {run.state === "AWAITING_REPAIR_APPROVAL" ? (
        <section className="decision-banner span-two">
          <div>
            <span className="section-label">Decision required</span>
            <h2>Review the diagnosis before generating a repair</h2>
            <p>Approval permits one bounded patch proposal. It does not execute, merge, or deploy code.</p>
          </div>
          <button className="button button-primary" type="button" onClick={onOpenApproval}>
            Review decision <ChevronRight size={16} />
          </button>
        </section>
      ) : null}
      <section className="panel conclusion-panel span-two">
        <div className="panel-head"><div><span className="section-label">Current conclusion</span><h2>{hypothesis?.summary ?? "Diagnosis has not completed"}</h2></div>{hypothesis ? <span className="confidence-label"><CircleDot size={13} />{humanize(hypothesis.confidence)} confidence</span> : null}</div>
        <div className="panel-body"><p className="lead-copy">{hypothesis?.mechanism ?? "IncidentLab is still collecting facts for this run."}</p></div>
      </section>
      <section className="summary-strip span-two">
        <div><span>State</span><strong>{stateLabels[run.state]}</strong><small>Updated {formatDate(run.updated_at)}</small></div>
        <div><span>Evidence</span><strong>{evidence.length} facts</strong><small>{evidence.filter((item) => item.kind === "gap").length} explicit gaps</small></div>
        <div><span>Candidates</span><strong>{candidates.length}</strong><small>{candidates.length ? "Policy accepted" : "None accepted"}</small></div>
        <div><span>Verification</span><strong className={top ? `text-${statusTone(top.outcome)}` : ""}>{top?.outcome ?? "Pending"}</strong><small>{top?.rank ? `Rank ${top.rank} · ${top.score_version}` : "No result yet"}</small></div>
        <div><span>Model usage</span><strong>{inputTokens + outputTokens} tokens</strong><small>{modelUsage.length} calls · ${estimatedCost.toFixed(6)}</small></div>
      </section>
      <section className="panel span-two">
        <div className="panel-head"><div><span className="section-label">Reproduction</span><h2>Observed incident facts</h2></div><Route size={18} /></div>
        <div className="panel-body fact-row">
          <div><span>Status sequence</span><strong>{Array.isArray(reproduction?.details.statuses) ? reproduction.details.statuses.join(" → ") : "Pending"}</strong></div>
          <div><span>Failure signal</span><strong>{typeof reproduction?.details.failure === "string" ? humanize(reproduction.details.failure) : "Pending"}</strong></div>
          <div><span>Pinned commit</span><strong><code>{shortId(run.pinned_commit)}</code></strong></div>
        </div>
      </section>
    </div>
  );
}

const evidenceIcons: Record<EvidenceItem["kind"], ReactNode> = {
  metric: <Gauge size={17} />,
  trace: <Route size={17} />,
  log: <TerminalSquare size={17} />,
  commit: <GitCommitHorizontal size={17} />,
  source: <FileCode2 size={17} />,
  gap: <AlertTriangle size={17} />,
};

function EvidenceTab({ items, onArtifact }: { items: EvidenceItem[]; onArtifact: (item: EvidenceItem) => void }) {
  const [kind, setKind] = useState<"all" | EvidenceItem["kind"]>("all");
  const [selectedId, setSelectedId] = useState("");
  if (!items.length) return <EmptyState icon={<Database size={24} />} title="No evidence recorded" detail="Evidence will appear after collection completes." />;
  const filtered = kind === "all" ? items : items.filter((item) => item.kind === kind);
  const selected = filtered.find((item) => item.id === selectedId) ?? filtered[0];
  const kinds = Array.from(new Set(items.map((item) => item.kind)));
  return (
    <div className="evidence-workspace">
      <aside className="evidence-browser">
        <div className="evidence-browser-head"><strong>Evidence</strong><span>{filtered.length} facts</span></div>
        <div className="evidence-filters" aria-label="Evidence type filters">
          <button type="button" className={kind === "all" ? "active" : ""} onClick={() => setKind("all")}>All</button>
          {kinds.map((value) => <button type="button" className={kind === value ? "active" : ""} key={value} onClick={() => setKind(value)}>{humanize(value)}</button>)}
        </div>
        <div className="evidence-list">
          {filtered.map((item) => (
            <button type="button" className={`evidence-list-item${selected?.id === item.id ? " active" : ""}${item.kind === "gap" ? " gap" : ""}`} key={item.id} onClick={() => setSelectedId(item.id)}>
              <span className="evidence-list-icon">{evidenceIcons[item.kind]}</span>
              <span><strong>{item.summary}</strong><small>{humanize(item.kind)} · {item.service}</small></span>
            </button>
          ))}
        </div>
      </aside>
      {selected ? (
        <article className="evidence-detail">
          <div className="evidence-detail-head">
            <div><span className="section-label">{humanize(selected.kind)} evidence</span><h2>{selected.summary}</h2></div>
            <button className="button button-small" type="button" onClick={() => onArtifact(selected)}>Open raw artifact</button>
          </div>
          <dl className="evidence-properties">
            <div><dt>Service</dt><dd>{selected.service}</dd></div>
            <div><dt>Source</dt><dd>{selected.source}</dd></div>
            <div><dt>Observed</dt><dd>{formatDate(selected.observed_start)}</dd></div>
            <div><dt>Retrieval</dt><dd>{humanize(selected.retrieval_method)}</dd></div>
          </dl>
          <div className="integrity-block"><ShieldCheck size={16} /><div><strong>Artifact integrity verified</strong><code>sha256:{selected.content_sha256}</code></div></div>
        </article>
      ) : <EmptyState icon={<Database size={24} />} title="No matching evidence" detail="Choose another evidence type." />}
    </div>
  );
}

function DiagnosisTab({ hypotheses, evidence }: {
  hypotheses: Awaited<ReturnType<typeof api.hypotheses>>;
  evidence: EvidenceItem[];
}) {
  const byId = new Map(evidence.map((item) => [item.id, item]));
  return (
    <div className="stack">
      {!hypotheses.length ? <EmptyState icon={<Search size={24} />} title="No validated diagnosis" detail="Hypotheses will appear after the diagnosis stage completes." /> : null}
      {hypotheses.map((hypothesis, index) => (
        <article className="panel" key={hypothesis.id}>
          <div className="panel-head"><div><span className="section-label">Hypothesis {index + 1} · {hypothesis.supporting_evidence_ids.length} supporting facts</span><h2>{hypothesis.summary}</h2></div><span className="confidence-label"><CircleDot size={13} />{humanize(hypothesis.confidence)} confidence</span></div>
          <div className="panel-body">
            <p className="lead-copy">{hypothesis.mechanism}</p>
            <div className="citation-columns">
              <CitationList title="Supporting evidence" ids={hypothesis.supporting_evidence_ids} byId={byId} tone="support" />
              <CitationList title="Contradicting evidence" ids={hypothesis.contradicting_evidence_ids} byId={byId} tone="contradict" />
            </div>
            <div className="provenance">Model <code>{hypothesis.model_id ?? "unknown"}</code> · Prompt <code>{hypothesis.prompt_version ?? "unknown"}</code></div>
          </div>
        </article>
      ))}
    </div>
  );
}

function ApprovalModal({ actor, setActor, approval, onClose }: {
  actor: string;
  setActor: (value: string) => void;
  approval: ReturnType<typeof useMutation<{ run_id: string; decision: string }, Error, "approved" | "rejected">>;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="modal approval-modal" role="dialog" aria-modal="true" aria-labelledby="approval-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div><span className="eyebrow">Human checkpoint</span><h2 id="approval-title">Generate a bounded repair?</h2></div>
          <button className="icon-button" type="button" aria-label="Close" onClick={onClose}><X size={18} /></button>
        </div>
        <p className="modal-lead">IncidentLab has completed diagnosis. Approving permits the configured OpenAI model to propose a small patch against the pinned commit. Deterministic policy and sandbox verification still run before anything is marked successful.</p>
        <div className="approval-safety"><ShieldCheck size={18} /><span>No merge, deployment, or model-provided command execution.</span></div>
        <label className="actor-field"><span>Decision recorded as</span><input value={actor} maxLength={128} onChange={(event) => setActor(event.target.value)} /></label>
        {approval.error ? <ErrorState error={approval.error} /> : null}
        <div className="modal-actions approval-modal-actions">
          <button className="button" type="button" disabled={approval.isPending || !actor.trim()} onClick={() => approval.mutate("rejected")}>Reject and close run</button>
          <button className="button button-primary" type="button" disabled={approval.isPending || !actor.trim()} onClick={() => approval.mutate("approved")}>
            {approval.isPending ? <LoaderCircle className="spin" size={16} /> : <ShieldCheck size={16} />} Approve repair generation
          </button>
        </div>
      </section>
    </div>
  );
}

function CitationList({ title, ids, byId, tone }: { title: string; ids: string[]; byId: Map<string, EvidenceItem>; tone: string }) {
  return <div className="citation-list"><h3>{title}</h3>{ids.length ? ids.map((id) => <div className={`citation citation-${tone}`} key={id}><span>{tone === "support" ? <Check size={14} /> : <AlertTriangle size={14} />}</span><div><strong>{byId.get(id)?.summary ?? id}</strong><small>{byId.get(id)?.kind ?? "unresolved"} · <code>{shortId(id, 12)}</code></small></div></div>) : <p className="muted-copy">None recorded.</p>}</div>;
}

function RepairTab({ candidates, events }: { candidates: RepairCandidate[]; events: AuditEvent[] }) {
  const [selected, setSelected] = useState(0);
  const candidate = candidates[selected] ?? candidates[0];
  const decisions = events.filter((event) => event.kind === "repair_policy_decision");
  if (!candidate) return <EmptyState icon={<Code2 size={24} />} title="No accepted repair" detail="An approved diagnosis must produce a policy-compliant candidate before a diff appears." />;
  return (
    <div className="repair-layout">
      <aside className="candidate-list">
        <span className="eyebrow">Candidates</span>
        {candidates.map((item, index) => <button className={index === selected ? "candidate-option active" : "candidate-option"} type="button" key={item.id} onClick={() => setSelected(index)}><span>Candidate {index + 1}</span><small>{shortId(item.diff_sha256, 12)}</small></button>)}
        <div className="policy-summary"><ShieldCheck size={17} /><div><strong>{candidate.policy_status}</strong><span>{candidate.policy_version}</span></div></div>
      </aside>
      <div className="stack">
        <section className="panel">
          <div className="panel-head"><div><span className="eyebrow">Expected change</span><h2>{candidate.explanation}</h2></div><StatusBadge value="accepted" label="Policy accepted" /></div>
          <div className="panel-body"><p className="lead-copy">{candidate.expected_behavior}</p><div className="metadata-grid"><span>Generator<strong>{candidate.generator_id}</strong></span><span>Changed path<strong>{candidate.changed_paths.join(", ")}</strong></span><span>Diff hash<strong><code>{shortId(candidate.diff_sha256, 16)}</code></strong></span></div></div>
        </section>
        <DiffViewer diff={candidate.unified_diff} />
        {decisions.length ? <section className="panel"><div className="panel-head"><h2>Policy decisions</h2><span className="muted-copy">{decisions.length} evaluated</span></div><div className="decision-list">{decisions.map((event) => <div className="decision-row" key={event.id}><StatusBadge value={event.details.accepted ? "PASS" : "FAIL"} label={event.details.accepted ? "Accepted" : "Rejected"} /><span>{String(event.details.category ?? "unknown")}</span><small>{String(event.details.detail ?? "")}</small></div>)}</div></section> : null}
      </div>
    </div>
  );
}

export function DiffViewer({ diff }: { diff: string }) {
  const lines = diff.split("\n");
  return <section className="diff-panel" aria-label="Unified diff"><div className="diff-head"><span><FileCode2 size={15} /> Unified diff</span><span>{lines.filter((line) => line.startsWith("+") && !line.startsWith("+++" )).length} additions · {lines.filter((line) => line.startsWith("-") && !line.startsWith("---")).length} deletions</span></div><pre>{lines.map((line, index) => <code className={line.startsWith("+") && !line.startsWith("+++") ? "diff-add" : line.startsWith("-") && !line.startsWith("---") ? "diff-del" : line.startsWith("@@") ? "diff-hunk" : ""} key={`${index}-${line}`}><span>{index + 1}</span>{line || " "}</code>)}</pre></section>;
}

function VerificationTab({ run, candidates, verifications, onArtifact }: { run: IncidentRun; candidates: RepairCandidate[]; verifications: VerificationRun[]; onArtifact: (check: VerificationCheck) => void }) {
  const ordered = [...verifications].sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));
  if (!ordered.length) return <EmptyState icon={run.state === "VERIFYING" ? <LoaderCircle className="spin" size={24} /> : <ListChecks size={24} />} title={run.state === "VERIFYING" ? "Sandbox verification is running" : "No verification recorded"} detail={run.state === "VERIFYING" ? "The trusted verifier is checking the baseline, build, tests, and repeated incident replay. This view updates automatically." : "Verification facts appear after a policy-accepted candidate reaches the sandbox."} />;
  return <div className="stack">{ordered.map((verification) => { const candidate = candidates.find((item) => item.id === verification.candidate_id); const passed = verification.checks.filter((check) => check.outcome === "PASS").length; return <article className="panel verification-panel" key={verification.id}><div className={`verification-result status-${statusTone(verification.outcome)}`}><span className="verification-result-icon">{verification.outcome === "PASS" ? <Check size={20} /> : verification.outcome === "FAIL" ? <OctagonX size={20} /> : <AlertTriangle size={20} />}</span><div><h2>Verification {humanize(verification.outcome).toLowerCase()}</h2><p>{passed} of {verification.checks.length} mandatory checks passed · candidate rank {verification.rank ?? "—"}</p></div></div><div className="panel-head"><div><span className="section-label">Candidate {candidate ? shortId(candidate.id) : shortId(verification.candidate_id)}</span><h2>{candidate?.explanation ?? "Repair candidate"}</h2></div></div><div className="verification-summary"><span>Score version<strong>{verification.score_version}</strong></span><span>Environment<strong><code>{shortId(verification.environment_digest.replace("sha256:", ""), 16)}</code></strong></span><span>Changed lines<strong>{verification.score?.changed_lines ?? "—"}</strong></span></div><div className="check-table"><div className="check-header"><span>Mandatory check</span><span>Duration</span><span>Exit</span><span>Outcome</span><span /></div>{verification.checks.map((check) => <VerificationRow key={check.name} check={check} onArtifact={onArtifact} />)}</div></article>;})}</div>;
}

function VerificationRow({ check, onArtifact }: { check: VerificationCheck; onArtifact: (check: VerificationCheck) => void }) {
  const duration = Math.max(0, new Date(check.finished_at).getTime() - new Date(check.started_at).getTime());
  return <div className="check-row"><span><span className={`check-icon status-${statusTone(check.outcome)}`}>{check.outcome === "PASS" ? <Check size={13} /> : check.outcome === "FAIL" ? <OctagonX size={13} /> : <AlertTriangle size={13} />}</span>{humanize(check.name)}{check.failure_reason ? <small>{humanize(check.failure_reason)}</small> : null}</span><span>{(duration / 1000).toFixed(1)}s</span><span>{check.exit_code ?? "—"}</span><StatusBadge value={check.outcome} /><button className="button button-small" type="button" onClick={() => onArtifact(check)}>View log</button></div>;
}

function AuditTab({ events }: { events: AuditEvent[] }) {
  if (!events.length) return <EmptyState icon={<ScrollText size={24} />} title="No audit events" detail="Durable workflow effects will appear here." />;
  return <section className="panel"><div className="panel-head"><div><span className="eyebrow">Immutable history</span><h2>Run audit trail</h2></div><span className="muted-copy">{events.length} events</span></div><div className="audit-list">{events.map((event) => <article className="audit-event" key={event.id}><div className="audit-time">{formatDate(event.created_at)}</div><span className="audit-marker" /><div><h3>{humanize(event.kind)}</h3><p>{event.actor} · <code>{shortId(event.correlation_id, 16)}</code></p><details><summary>Event details</summary><pre>{JSON.stringify(event.details, null, 2)}</pre></details></div></article>)}</div></section>;
}

function ArtifactModal({ title, artifactRef, onClose }: { title: string; artifactRef: string; onClose: () => void }) {
  const artifact = useQuery({ queryKey: ["artifact", artifactRef], queryFn: () => api.artifactText(artifactRef) });
  return <div className="modal-backdrop" role="presentation" onMouseDown={onClose}><section className="modal artifact-modal" role="dialog" aria-modal="true" aria-labelledby="artifact-title" onMouseDown={(event) => event.stopPropagation()}><div className="modal-head"><div><span className="eyebrow">Hash-verified raw data</span><h2 id="artifact-title">{title}</h2></div><button className="icon-button" type="button" aria-label="Close" onClick={onClose}><X size={18} /></button></div>{artifact.isLoading ? <PageLoader label="Loading artifact" /> : null}{artifact.error ? <ErrorState error={artifact.error} /> : null}{artifact.data ? <pre className="artifact-content">{artifact.data}</pre> : null}</section></div>;
}

export function App() {
  return <Routes><RouterRoute path="/runs" element={<RunsPage />} /><RouterRoute path="/runs/:runId" element={<RunDetailPage />} /><RouterRoute path="*" element={<Navigate to="/runs" replace />} /></Routes>;
}
