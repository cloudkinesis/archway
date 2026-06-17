import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  BookOpen,
  Bot,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Database,
  Download,
  DollarSign,
  ExternalLink,
  FileText,
  Gauge,
  HeartPulse,
  History,
  Image,
  Layers,
  LayoutDashboard,
  ListChecks,
  Loader2,
  Lock,
  MessageSquareText,
  Minus,
  Move,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  X
} from "lucide-react";
import { api, artifactUrl } from "../lib/api";
import { TrustPanel } from "./TrustPanel";
import type { ArchitectureRevision, ArchitectureSpec, ArchitectureValidationIssue, BuildStatusSummary, DiagramGalleryResult, ExportBundle, HealthCheckResult, HealthSummary, JobRun, LiveAgentStatus, PricingCheckpoint, PricingViewModel, Readiness, ResearchDigest, ResearchNarrative, ResearchReport, ResearchViewModel, Session } from "../lib/types";
import { sanitizeMarkdown } from "../lib/markdown";

type View = "synthesis" | "research" | "architecture" | "diagrams" | "diagnostics";
type ArchitectureDraft = Pick<ArchitectureSpec, "summary" | "scaling_strategy" | "resilience_strategy" | "cost_optimization_strategy"> & {
  security_controls_text: string;
  observability_controls_text: string;
};

export function App() {
  const queryClient = useQueryClient();
  const [healthAccepted, setHealthAccepted] = useState(false);
  const [activeSession, setActiveSession] = useState<Session | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [view, setView] = useState<View>("synthesis");
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [researchNarrative, setResearchNarrative] = useState<ResearchNarrative | null>(null);
  const [researchDigest, setResearchDigest] = useState<ResearchDigest | null>(null);
  const [researchViewModel, setResearchViewModel] = useState<ResearchViewModel | null>(null);
  const [architectures, setArchitectures] = useState<ArchitectureSpec[]>([]);
  const [architectureValidationIssues, setArchitectureValidationIssues] = useState<ArchitectureValidationIssue[]>([]);
  const [architectureRevisions, setArchitectureRevisions] = useState<ArchitectureRevision[]>([]);
  const [galleries, setGalleries] = useState<DiagramGalleryResult[]>([]);
  const [latestExport, setLatestExport] = useState<ExportBundle | null>(null);

  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: healthAccepted ? false : 8000 });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: api.listSessions, enabled: healthAccepted });
  const hydration = useQuery({
    queryKey: ["session-hydration", activeSession?.id],
    queryFn: () => api.hydrateSession(activeSession?.id as string),
    enabled: healthAccepted && Boolean(activeSession)
  });

  useEffect(() => {
    const data = hydration.data;
    if (!data) return;
    setActiveSession(data.session);
    setReadiness(data.readiness ?? null);
    setReport(data.research ?? null);
    setResearchNarrative(data.research_narrative ?? null);
    setResearchDigest(data.research_digest ?? null);
    setResearchViewModel(data.research_view_model ?? null);
    setArchitectures(data.architecture?.architectures ?? []);
    setArchitectureValidationIssues(data.architecture?.validation_issues ?? []);
    setArchitectureRevisions(data.architecture?.revisions ?? []);
    setGalleries(data.diagrams ?? []);
    setLatestExport(data.diagnostics?.latest_export ?? null);
  }, [hydration.data]);

  if (!healthAccepted) {
    return <HealthGate health={health.data} loading={health.isLoading} error={health.error as Error | null} onRetry={() => health.refetch()} onContinue={() => setHealthAccepted(true)} />;
  }

  return (
    <div className="min-h-screen bg-background text-awsTextPrimary">
      <TopBar health={health.data} />
      <div className="grid min-h-[calc(100vh-64px)] grid-cols-[280px_minmax(0,1fr)_340px] max-xl:grid-cols-[250px_minmax(0,1fr)] max-lg:grid-cols-1">
        <SessionSidebar
          sessions={sessions.data?.sessions ?? []}
          activeSession={activeSession}
          onSelect={(session) => {
            setActiveSession(session);
            setReadiness(null);
            setReport(null);
            setResearchNarrative(null);
            setResearchDigest(null);
            setResearchViewModel(null);
            setArchitectures([]);
            setArchitectureValidationIssues([]);
            setArchitectureRevisions([]);
            setGalleries([]);
            setLatestExport(null);
            setView("synthesis");
          }}
          onCreated={(session, nextReadiness) => {
            setActiveSession(session);
            setReadiness(nextReadiness);
            setView("synthesis");
            queryClient.invalidateQueries({ queryKey: ["sessions"] });
          }}
        />
        <main className="min-w-0 border-x border-awsBorder/70 bg-[#f8fafc]">
          {!activeSession ? (
            <EmptyWorkspace />
          ) : (
            <Workspace
              session={activeSession}
              setSession={setActiveSession}
              readiness={readiness}
              setReadiness={setReadiness}
              view={view}
              setView={setView}
              report={report}
              setReport={setReport}
              researchNarrative={researchNarrative}
              setResearchNarrative={setResearchNarrative}
              researchDigest={researchDigest}
              setResearchDigest={setResearchDigest}
              researchViewModel={researchViewModel}
              setResearchViewModel={setResearchViewModel}
              architectures={architectures}
              setArchitectures={setArchitectures}
              architectureValidationIssues={architectureValidationIssues}
              setArchitectureValidationIssues={setArchitectureValidationIssues}
              architectureRevisions={architectureRevisions}
              setArchitectureRevisions={setArchitectureRevisions}
              galleries={galleries}
              setGalleries={setGalleries}
              latestExport={latestExport}
              setLatestExport={setLatestExport}
              hydrationLoading={hydration.isFetching}
              hydrationError={hydration.error as Error | null}
            />
          )}
        </main>
        <aside className="max-xl:hidden">
          <SolutionBrief session={activeSession} readiness={readiness} />
        </aside>
      </div>
    </div>
  );
}

function HealthGate({ health, loading, error, onRetry, onContinue }: { health?: HealthSummary; loading: boolean; error: Error | null; onRetry: () => void; onContinue: () => void }) {
  const requiredBlocked = health?.checks.some((check) => check.required && check.status === "failed") ?? true;
  const optionalDegraded = health?.checks.some((check) => !check.required && check.status !== "ready") ?? false;
  return (
    <div className="min-h-screen bg-background px-6 py-8 text-awsTextPrimary">
      <div className="mx-auto max-w-6xl">
        <div className="mb-8 flex items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <div className="grid h-11 w-11 place-items-center border border-awsOrange/50 bg-white shadow-console">
                <Sparkles className="h-6 w-6 text-awsOrange" />
              </div>
              <div>
                <h1 className="text-3xl font-semibold tracking-normal">Archway</h1>
                <p className="text-sm text-awsTextMuted">Startup health check</p>
              </div>
            </div>
          </div>
          <StatusPill status={health?.status ?? "degraded"} />
        </div>
        {error ? <Banner tone="danger" text={error.message} /> : null}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(health?.checks ?? skeletonChecks).map((check) => (
            <HealthCard key={check.id} check={check} loading={loading && !health} />
          ))}
        </div>
        <div className="mt-6 flex flex-wrap items-center gap-3 border border-awsBorder bg-surface p-4">
          <Button icon={RefreshCw} onClick={onRetry} variant="secondary">Retry checks</Button>
          <Button icon={FileText} variant="secondary">View diagnostics</Button>
          <Button icon={ChevronRight} disabled={requiredBlocked} onClick={onContinue}>{requiredBlocked || optionalDegraded ? "Continue with notices" : "Start Archway"}</Button>
          <span className="text-sm text-awsTextMuted">
            {optionalDegraded
              ? "Optional notices are visible above; required product capabilities are checked separately."
              : "All required and configured optional product capabilities are ready."}
          </span>
        </div>
      </div>
    </div>
  );
}

function HealthCard({ check, loading }: { check: HealthCheckResult; loading?: boolean }) {
  const Icon = check.status === "ready" ? CheckCircle2 : check.status === "failed" ? TriangleAlert : AlertTriangle;
  return (
    <div className="min-h-[148px] border border-awsBorder bg-surface p-4 shadow-console">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          {loading ? <Loader2 className="h-5 w-5 animate-spin text-awsTextMuted" /> : <Icon className={statusClass(check.status)} />}
          <h2 className="text-sm font-semibold">{check.label}</h2>
        </div>
        <span className="text-xs text-awsTextMuted">{check.required ? "Required" : "Optional"}</span>
      </div>
      <StatusPill status={check.status} />
      <p className="mt-3 text-sm leading-6 text-awsTextSecondary">{check.reason}</p>
    </div>
  );
}

function TopBar({ health }: { health?: HealthSummary }) {
  const modelLabel = activeModelLabel(health);
  return (
    <header className="flex h-16 items-center justify-between border-b border-[#1b2533] bg-awsSquidInk px-5 text-white">
      <div className="flex items-center gap-3">
        <div className="grid h-9 w-9 place-items-center border border-awsOrange/60 bg-[#161e2d]">
          <Sparkles className="h-5 w-5 text-awsOrange" />
        </div>
        <div>
          <div className="font-semibold">Archway</div>
          <div className="text-xs text-slate-300">AWS solution architecture assistant</div>
        </div>
      </div>
      <div className="flex items-center gap-3 text-sm">
        <StatusPill status={health?.status ?? "degraded"} />
        <span className="hidden text-slate-300 md:inline">{modelLabel}</span>
        <Button icon={Settings} variant="ghost" ariaLabel="Settings" />
      </div>
    </header>
  );
}

function activeModelLabel(health?: HealthSummary) {
  const checks = health?.checks ?? [];
  const bedrock = checks.find((check) => check.id === "bedrock_sonnet");
  if (bedrock?.status === "ready") {
    const modelId = typeof bedrock.details?.model_id === "string" ? bedrock.details.model_id : "Nova Pro";
    return `Model: ${modelId}`;
  }
  const ollama = checks.find((check) => check.id === "ollama");
  if (ollama?.status === "ready") {
    const model = typeof ollama.details?.model === "string" ? ollama.details.model : "local Ollama";
    return `Model: ${model}`;
  }
  return "Model: deterministic fallback";
}

function SessionSidebar({ sessions, activeSession, onSelect, onCreated }: { sessions: Session[]; activeSession: Session | null; onSelect: (session: Session) => void; onCreated: (session: Session, readiness: Readiness) => void }) {
  const [useCase, setUseCase] = useState("");
  const create = useMutation({
    mutationFn: api.createSession,
    onSuccess: ({ session, readiness }) => onCreated(session, readiness)
  });
  const example = "I want to build an AI assistant for retail customers that can answer order questions, check delivery status, and help support agents resolve issues faster.";
  return (
    <aside className="border-r border-awsBorder bg-[#eef2f7] p-4 max-lg:border-b">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-awsTextMuted">Sessions</h2>
        <Button icon={Search} variant="ghost" ariaLabel="Search sessions" />
      </div>
      <div className="mb-5 border border-awsBorder bg-surface p-3">
        <textarea
          value={useCase}
          onChange={(event) => setUseCase(event.target.value)}
          className="h-36 w-full resize-none border border-awsBorder bg-white p-3 text-sm leading-6 text-awsTextPrimary outline-none focus:border-awsOrange"
          placeholder={'Describe the AI use case you want to build. For example: "I want to build an AI assistant for retail customers..."'}
        />
        <div className="mt-2 flex items-center justify-between text-xs text-awsTextMuted">
          <span>{useCase.length} characters</span>
          <button onClick={() => setUseCase(example)} className="text-awsOrange">Load example</button>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Button icon={Sparkles} disabled={useCase.trim().length < 3 || create.isPending} onClick={() => create.mutate(useCase)}>Start</Button>
          <Button icon={RefreshCw} variant="secondary" onClick={() => setUseCase("")}>Clear</Button>
        </div>
      </div>
      <div className="archway-scroll max-h-[calc(100vh-330px)] space-y-2 overflow-y-auto">
        {sessions.map((session) => (
          <button
            key={session.id}
            onClick={() => onSelect(session)}
            className={`w-full border p-3 text-left transition ${activeSession?.id === session.id ? "border-awsOrange bg-awsPanelSoft" : "border-awsBorder bg-surface hover:border-awsTextMuted"}`}
          >
            <div className="line-clamp-2 text-sm font-medium">{session.name}</div>
            <div className="mt-2 flex items-center justify-between text-xs text-awsTextMuted">
              <span>{session.active_phase}</span>
              <span className="rounded-sm border border-awsBorder px-2 py-0.5">{session.status}</span>
            </div>
          </button>
        ))}
      </div>
    </aside>
  );
}

function Workspace(props: {
  session: Session;
  setSession: (session: Session) => void;
  readiness: Readiness | null;
  setReadiness: (readiness: Readiness | null) => void;
  view: View;
  setView: (view: View) => void;
  report: ResearchReport | null;
  setReport: (report: ResearchReport | null) => void;
  researchNarrative: ResearchNarrative | null;
  setResearchNarrative: (narrative: ResearchNarrative | null) => void;
  researchDigest: ResearchDigest | null;
  setResearchDigest: (digest: ResearchDigest | null) => void;
  researchViewModel: ResearchViewModel | null;
  setResearchViewModel: (viewModel: ResearchViewModel | null) => void;
  architectures: ArchitectureSpec[];
  setArchitectures: (items: ArchitectureSpec[]) => void;
  architectureValidationIssues: ArchitectureValidationIssue[];
  setArchitectureValidationIssues: (items: ArchitectureValidationIssue[]) => void;
  architectureRevisions: ArchitectureRevision[];
  setArchitectureRevisions: (items: ArchitectureRevision[]) => void;
  galleries: DiagramGalleryResult[];
  setGalleries: (items: DiagramGalleryResult[]) => void;
  latestExport: ExportBundle | null;
  setLatestExport: (bundle: ExportBundle | null) => void;
  hydrationLoading: boolean;
  hydrationError: Error | null;
}) {
  const tabs: Array<[View, string, typeof MessageSquareText]> = [
    ["synthesis", "Synthesis", MessageSquareText],
    ["research", "Research", ClipboardList],
    ["architecture", "Architecture", LayoutDashboard],
    ["diagrams", "Diagrams", Image],
    ["diagnostics", "Diagnostics", Activity]
  ];
  return (
    <div className="flex min-h-full flex-col">
      <nav className="sticky top-0 z-30 flex gap-1 border-b border-awsBorder bg-surface px-4 py-3">
        {tabs.map(([id, label, Icon]) => (
          <button key={id} onClick={() => props.setView(id)} className={`flex items-center gap-2 border px-3 py-2 text-sm ${props.view === id ? "border-awsOrange bg-awsPanelSoft text-awsTextPrimary" : "border-transparent text-awsTextMuted hover:border-awsBorder"}`}>
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </nav>
      {props.hydrationLoading ? <div className="border-b border-awsBorder bg-[#eef6ff] px-5 py-2 text-xs text-awsTextSecondary">Loading saved session artifacts...</div> : null}
      {props.hydrationError ? <div className="border-b border-awsDanger/40 bg-[#fff1f2] px-5 py-2 text-xs text-awsDanger">Could not hydrate saved session: {props.hydrationError.message}</div> : null}
      {props.view === "synthesis" ? <SynthesisView {...props} /> : null}
      {props.view === "research" ? <ResearchView {...props} /> : null}
      {props.view === "architecture" ? <ArchitectureView {...props} /> : null}
      {props.view === "diagrams" ? <DiagramView {...props} /> : null}
      {props.view === "diagnostics" ? <DiagnosticsView {...props} /> : null}
    </div>
  );
}

function SynthesisView({ session, setSession, readiness, setReadiness, setView }: Parameters<typeof Workspace>[0]) {
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<Array<{ role: "user" | "assistant"; text: string }>>([]);
  const [showJumpLatest, setShowJumpLatest] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const opening = interviewPromptFromReadiness(readiness);
  useEffect(() => {
    setTurns(interviewTurnsFromSession(session, opening));
    setMessage("");
    setShowJumpLatest(false);
  }, [session.id, opening]);
  useEffect(() => {
    if (!showJumpLatest) {
      endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [turns.length]);
  const scrollToLatest = () => {
    setShowJumpLatest(false);
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  };
  const onConversationScroll = () => {
    const element = scrollRef.current;
    if (!element) return;
    const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    setShowJumpLatest(distanceFromBottom > 160);
  };
  const send = useMutation({
    mutationFn: () => api.sendSynthesis(session.id, message),
    onSuccess: (result) => {
      const userText = message;
      setSession({ ...session, current_summary: result.brief });
      setReadiness(result.readiness);
      setTurns((current) => [...current, { role: "user", text: userText }, { role: "assistant", text: result.message }]);
      setMessage("");
    }
  });
  const proceed = useMutation({
    mutationFn: (assume: boolean) => api.proceed(session.id, assume),
    onSuccess: (result) => {
      setReadiness(result.readiness);
      if (!result.proceeded) {
        setTurns((current) => [...current, { role: "assistant", text: result.message }]);
      }
      if (result.proceeded) setView("research");
    }
  });
  const interviewCount = interviewTurnCount(session);
  const showOptionalProceed = interviewCount >= 4 || !readiness?.recommended_minimum_questions.length;
  return (
    <section className="flex h-[calc(100vh-113px)] flex-1 flex-col bg-[#f8fafc]">
      <div className="border-b border-awsBorder bg-surface px-6 py-3">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold"><MessageSquareText className="h-4 w-4 text-awsOrange" /> Interview</div>
            <p className="mt-1 text-xs text-awsTextMuted">Answers feed the brief, research, pricing, architecture, diagrams, and export package.</p>
          </div>
          <span className="border border-awsBorder bg-white px-2 py-1 text-xs text-awsTextMuted">{interviewCount} answers captured</span>
        </div>
      </div>
      <div ref={scrollRef} onScroll={onConversationScroll} className="archway-scroll relative flex-1 overflow-y-auto px-5 py-5">
        <div className="mx-auto space-y-4 pb-4">
          {turns.map((turn, index) => <ConversationBubble key={`${turn.role}-${index}`} role={turn.role} text={turn.text} />)}
          {readiness && showOptionalProceed ? <Checkpoint readiness={readiness} onAssume={() => proceed.mutate(true)} /> : null}
          <div ref={endRef} />
        </div>
        {showJumpLatest ? (
          <button onClick={scrollToLatest} className="sticky bottom-3 mx-auto flex border border-awsBorder bg-white px-3 py-2 text-sm font-semibold text-awsTextSecondary shadow-console hover:border-awsOrange">
            Jump to latest
          </button>
        ) : null}
      </div>
      <div className="sticky bottom-0 border-t border-awsBorder bg-white px-5 py-4 shadow-console">
        <div className="mx-auto max-w-5xl">
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && message.trim() && !send.isPending) {
                send.mutate();
              }
            }}
            className="min-h-28 w-full resize-y border border-awsBorder bg-white p-4 text-base leading-7 text-awsTextPrimary outline-none focus:border-awsOrange"
            placeholder="Answer here. Add constraints, systems, approval rules, numbers, or say what is unknown."
            disabled={send.isPending || proceed.isPending}
          />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div className="text-xs text-awsTextMuted">Natural language is fine. Short answers are fine too.</div>
            <div className="flex flex-wrap gap-2">
              <Button icon={MessageSquareText} disabled={!message.trim() || send.isPending} onClick={() => send.mutate()} variant="secondary">{send.isPending ? "Capturing" : "Send Answer"}</Button>
              <Button icon={ChevronRight} disabled={proceed.isPending} onClick={() => proceed.mutate(showOptionalProceed)}>{showOptionalProceed ? "Proceed to Research" : "Ask Next Question"}</Button>
            </div>
          </div>
          {send.error ? <Banner tone="danger" text={(send.error as Error).message} /> : null}
          {proceed.error ? <Banner tone="danger" text={(proceed.error as Error).message} /> : null}
        </div>
      </div>
    </section>
  );
}

function ResearchView({ session, report, setReport, researchNarrative, setResearchNarrative, researchDigest, setResearchDigest, researchViewModel, setResearchViewModel, setView }: Parameters<typeof Workspace>[0]) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [researchDepth, setResearchDepth] = useState("deep_dossier");
  const job = useJobPolling(session.id, jobId, async () => {
    const result = await api.hydrateSession(session.id);
    setReport(result.research ?? null);
    setResearchNarrative(result.research_narrative ?? null);
    setResearchDigest(result.research_digest ?? null);
    setResearchViewModel(result.research_view_model ?? null);
  });
  const run = useMutation({ mutationFn: () => api.runResearch(session.id), onSuccess: (result) => setJobId(result.job.id) });
  return (
    <Panel title="Research" icon={ClipboardList}>
      {!report ? (
        <div className="space-y-4">
          <div className="grid gap-3 border border-awsBorder bg-surface p-4 md:grid-cols-[240px_1fr]">
            <label className="text-sm font-semibold" htmlFor="research-depth">Research depth</label>
            <select
              id="research-depth"
              value={researchDepth}
              onChange={(event) => setResearchDepth(event.target.value)}
              className="border border-awsBorder bg-white px-3 py-2 text-sm text-awsTextPrimary"
            >
              <option value="deep_dossier">Deep dossier</option>
              <option value="standard_research">Standard research</option>
              <option value="quick_brief">Quick brief</option>
            </select>
            <div className="md:col-start-2">
              <Banner tone="info" text="Deep dossier mode produces a narrative executive summary, claim register, evidence map, pricing trace, consistency check, and customer-readiness gate in the export package." />
            </div>
          </div>
          <ProgressTimeline active={run.isPending || job.isActive} />
          {job.job ? <JobProgress job={job.job} onCancel={() => job.cancel.mutate()} /> : null}
          <Button icon={run.isPending || job.isActive ? Loader2 : Sparkles} disabled={run.isPending || job.isActive} onClick={() => run.mutate()}>{run.isPending || job.isActive ? "Research running" : "Run evidence-grounded research"}</Button>
          {run.error ? <Banner tone="danger" text={(run.error as Error).message} /> : null}
          {job.job?.status === "failed" ? <Banner tone="danger" text={job.job.error ?? "Research failed. Diagnostics were recorded."} /> : null}
        </div>
      ) : (
        <Report session={session} report={report} narrative={researchNarrative} digest={researchDigest} viewModel={researchViewModel} onReportUpdated={setReport} onNarrativeUpdated={setResearchNarrative} onDigestUpdated={setResearchDigest} onViewModelUpdated={setResearchViewModel} onNext={() => setView("architecture")} />
      )}
    </Panel>
  );
}

function ArchitectureView({
  session,
  architectures,
  setArchitectures,
  architectureValidationIssues,
  setArchitectureValidationIssues,
  architectureRevisions,
  setArchitectureRevisions,
  setGalleries,
  setView
}: Parameters<typeof Workspace>[0]) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, ArchitectureDraft>>({});
  const job = useJobPolling(session.id, jobId, async () => {
    const result = await api.getArchitecture(session.id);
    setArchitectures(result.architectures);
    setArchitectureValidationIssues(result.validation_issues ?? []);
    setArchitectureRevisions(result.revisions ?? []);
  });
  const generate = useMutation({ mutationFn: () => api.generateArchitecture(session.id), onSuccess: (result) => setJobId(result.job.id) });
  const save = useMutation({
    mutationFn: () => api.updateArchitecture(session.id, {
      reason: "User-edited architecture revision",
      specs: Object.fromEntries(architectures.map((architecture) => [architecture.mode, draftToPatch(drafts[architecture.mode] ?? architectureToDraft(architecture))]))
    }),
    onSuccess: (result) => {
      setArchitectures(result.architectures);
      setArchitectureValidationIssues(result.validation_issues ?? []);
      setArchitectureRevisions(result.revisions ?? []);
      setGalleries([]);
    }
  });
  const regenerate = useMutation({
    mutationFn: () => api.regenerateArchitecture(session.id),
    onSuccess: (result) => {
      setArchitectures(result.architectures);
      setArchitectureValidationIssues(result.validation_issues ?? []);
      setArchitectureRevisions(result.revisions ?? []);
      setGalleries([]);
    }
  });

  useEffect(() => {
    if (architectures.length === 0) {
      setDrafts({});
      return;
    }
    setDrafts(Object.fromEntries(architectures.map((architecture) => [architecture.mode, architectureToDraft(architecture)])));
  }, [architectures]);

  const hasCriticalIssues = architectureValidationIssues.some((issue) => issue.severity === "critical");

  return (
    <Panel title="Architecture" icon={LayoutDashboard}>
      {architectures.length === 0 ? (
        <div className="space-y-4">
          {job.job ? <JobProgress job={job.job} onCancel={() => job.cancel.mutate()} /> : null}
          <Button icon={generate.isPending || job.isActive ? Loader2 : LayoutDashboard} disabled={generate.isPending || job.isActive} onClick={() => generate.mutate()}>{generate.isPending || job.isActive ? "Planning" : "Generate POC and production specs"}</Button>
          {job.job?.status === "failed" ? <Banner tone="danger" text={job.job.error ?? "Architecture planning failed. Diagnostics were recorded."} /> : null}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 border border-awsBorder bg-surface p-4">
            <div>
              <div className="font-semibold">Revision {architectureRevisions[architectureRevisions.length - 1]?.version ?? 1}</div>
              <p className="text-sm text-awsTextSecondary">Edits are saved as new revisions and diagrams regenerate only from the active revision.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button icon={regenerate.isPending ? Loader2 : RotateCcw} variant="secondary" disabled={regenerate.isPending || save.isPending} onClick={() => regenerate.mutate()}>Regenerate from active</Button>
              <Button icon={save.isPending ? Loader2 : Save} disabled={save.isPending || regenerate.isPending} onClick={() => save.mutate()}>Save revision</Button>
            </div>
          </div>
          <ValidationPanel issues={architectureValidationIssues} />
          {architectures.map((architecture) => (
            <ArchitectureEditorCard
              key={architecture.id}
              architecture={architecture}
              draft={drafts[architecture.mode] ?? architectureToDraft(architecture)}
              onChange={(draft) => setDrafts((current) => ({ ...current, [architecture.mode]: draft }))}
            />
          ))}
          <div className="flex flex-wrap items-center gap-3">
            <Button icon={ChevronRight} onClick={() => setView("diagrams")}>
              {hasCriticalIssues ? "Proceed to Diagnostic Diagrams" : "Proceed to Diagrams"}
            </Button>
            {hasCriticalIssues ? (
              <span className="text-sm text-awsTextSecondary">
                Critical findings will generate candidate diagnostic diagrams with the blockers attached; export can still complete.
              </span>
            ) : null}
          </div>
          {save.error ? <Banner tone="danger" text={(save.error as Error).message} /> : null}
          {regenerate.error ? <Banner tone="danger" text={(regenerate.error as Error).message} /> : null}
          {architectureRevisions.length > 1 ? <RevisionHistory revisions={architectureRevisions} /> : null}
        </div>
      )}
    </Panel>
  );
}

function DiagramView({ session, galleries, setGalleries }: Parameters<typeof Workspace>[0]) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [selected, setSelected] = useState<{
    gallery: DiagramGalleryResult;
    diagram: DiagramGalleryResult["diagrams"][number];
    qa?: DiagramGalleryResult["qa_reports"][number];
  } | null>(null);
  const job = useJobPolling(session.id, jobId, async () => {
    const result = await api.getDiagrams(session.id);
    setGalleries(result.galleries);
  });
  const generate = useMutation({ mutationFn: () => api.generateDiagrams(session.id), onSuccess: (result) => setJobId(result.job.id) });
  return (
    <Panel title="Diagram Gallery" icon={Image}>
      {galleries.length === 0 ? (
        <div className="space-y-4">
          {job.job ? <JobProgress job={job.job} onCancel={() => job.cancel.mutate()} /> : null}
          <Button icon={generate.isPending || job.isActive ? Loader2 : Image} disabled={generate.isPending || job.isActive} onClick={() => generate.mutate()}>{generate.isPending || job.isActive ? "Generating through existing compiler" : "Generate diagrams"}</Button>
          <Banner tone="info" text="If architecture validation still has blockers, Archway generates candidate diagnostic diagrams instead of stopping the session." />
          {job.job?.status === "failed" ? <Banner tone="danger" text={job.job.error ?? "Diagram generation failed. Diagnostics were recorded."} /> : null}
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {galleries.flatMap((gallery) => gallery.diagrams.map((diagram) => {
            const qa = gallery.qa_reports.find((item) => item.view_id === (diagram.compiler_view_id ?? diagram.view_id));
            const status = qa?.passed === false ? "degraded" : "ready";
            return (
            <div key={diagram.id} className="border border-awsBorder bg-surface p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h3 className="font-semibold">{diagram.title}</h3>
                  <p className="text-sm text-awsTextMuted">{gallery.mode} · {diagram.view_id}{diagram.rendered_as_native_view === false ? " · mapped through compiler support" : ""}</p>
                  {diagram.user_description ? <p className="mt-1 text-sm text-awsTextSecondary">{diagram.user_description}</p> : null}
                  {diagram.fallback_reason ? <p className="mt-1 text-xs text-awsTextMuted">{diagram.fallback_reason}</p> : null}
                </div>
                <StatusPill status={status} />
              </div>
              {diagram.preview_svg_artifact_id ? (
                <button
                  className="group block w-full border border-awsBorder bg-white focus:border-awsOrange focus:outline-none"
                  onClick={() => setSelected({ gallery, diagram, qa })}
                  aria-label={`Open ${diagram.title}`}
                >
                  <img className="max-h-80 w-full object-contain transition group-hover:opacity-90" src={artifactUrl(session.id, diagram.preview_svg_artifact_id)} alt={diagram.title} />
                  <span className="block border-t border-awsBorder bg-awsPanelSoft px-3 py-2 text-left text-xs text-awsTextSecondary">Click to inspect full-size diagram</span>
                </button>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2">
                {Object.entries(diagram.format_paths).map(([format, artifact]) => (
                  <a key={format} href={artifactUrl(session.id, artifact)} className="inline-flex items-center gap-2 border border-awsBorder px-3 py-2 text-sm text-awsTextSecondary hover:border-awsOrange">
                    <Download className="h-4 w-4" /> {format.toUpperCase()}
                  </a>
                ))}
              </div>
            </div>
          ); }))}
        </div>
      )}
      {generate.error ? <Banner tone="danger" text={(generate.error as Error).message} /> : null}
      {selected ? <DiagramInspector sessionId={session.id} selection={selected} onClose={() => setSelected(null)} /> : null}
    </Panel>
  );
}

function DiagramInspector({
  sessionId,
  selection,
  onClose
}: {
  sessionId: string;
  selection: {
    gallery: DiagramGalleryResult;
    diagram: DiagramGalleryResult["diagrams"][number];
    qa?: DiagramGalleryResult["qa_reports"][number];
  };
  onClose: () => void;
}) {
  const [zoom, setZoom] = useState(1);
  const diagram = selection.diagram;
  const svgArtifact = diagram.format_paths.svg ?? diagram.preview_svg_artifact_id;
  const d2Artifact = diagram.format_paths.d2;
  const qualityStatus = selection.qa?.passed === false ? "degraded" : "ready";
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 bg-[#0f172a]/70 p-4">
      <div className="flex h-full flex-col border border-awsBorder bg-white shadow-console">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-awsBorder bg-surface px-4 py-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-lg font-semibold">{diagram.title}</h3>
              <StatusPill status={qualityStatus} />
            </div>
            <p className="mt-1 text-sm text-awsTextMuted">
              {selection.gallery.mode} · view {diagram.view_id}{diagram.compiler_view_id ? ` · compiler ${diagram.compiler_view_id}` : ""}
            </p>
            {diagram.fallback_reason ? <p className="mt-1 text-sm text-awsTextSecondary">Degraded reason: {diagram.fallback_reason}</p> : null}
            {selection.qa?.diagnostics?.length ? <p className="mt-1 text-sm text-awsTextSecondary">QA diagnostics: {JSON.stringify(selection.qa.diagnostics)}</p> : null}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button icon={Minus} variant="secondary" onClick={() => setZoom((value) => Math.max(0.35, Number((value - 0.15).toFixed(2))))} ariaLabel="Zoom out" />
            <Button icon={Move} variant="secondary" onClick={() => setZoom(1)}>Fit to screen</Button>
            <Button icon={Plus} variant="secondary" onClick={() => setZoom((value) => Math.min(3, Number((value + 0.15).toFixed(2))))} ariaLabel="Zoom in" />
            {svgArtifact ? <a href={artifactUrl(sessionId, svgArtifact)} target="_blank" rel="noreferrer" className="inline-flex min-h-10 items-center justify-center gap-2 border border-awsBorder bg-awsPanelSoft px-3 py-2 text-sm font-semibold text-awsTextPrimary hover:border-awsOrange"><ExternalLink className="h-4 w-4" /> New tab</a> : null}
            {svgArtifact ? <a href={artifactUrl(sessionId, svgArtifact)} download className="inline-flex min-h-10 items-center justify-center gap-2 border border-awsBorder bg-awsPanelSoft px-3 py-2 text-sm font-semibold text-awsTextPrimary hover:border-awsOrange"><Download className="h-4 w-4" /> SVG</a> : null}
            {d2Artifact ? <a href={artifactUrl(sessionId, d2Artifact)} download className="inline-flex min-h-10 items-center justify-center gap-2 border border-awsBorder bg-awsPanelSoft px-3 py-2 text-sm font-semibold text-awsTextPrimary hover:border-awsOrange"><Download className="h-4 w-4" /> D2</a> : null}
            <Button icon={X} variant="secondary" onClick={onClose} ariaLabel="Close diagram viewer" />
          </div>
        </div>
        <div className="archway-scroll flex-1 overflow-auto bg-[#f8fafc] p-6">
          {svgArtifact ? (
            <div className="mx-auto w-fit min-w-full text-center">
              <img
                src={artifactUrl(sessionId, svgArtifact)}
                alt={diagram.title}
                className="inline-block max-w-none border border-awsBorder bg-white shadow-console"
                style={{ width: `${Math.round(100 * zoom)}%`, minWidth: zoom > 1 ? `${Math.round(100 * zoom)}%` : undefined }}
              />
            </div>
          ) : (
            <div className="border border-awsBorder bg-white p-4 text-sm text-awsTextMuted">No SVG artifact is available for this diagram.</div>
          )}
        </div>
      </div>
    </div>
  );
}

function useJobPolling(sessionId: string, jobId: string | null, onSucceeded: () => Promise<void>) {
  const [completedJobId, setCompletedJobId] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["job", sessionId, jobId],
    queryFn: () => api.getJob(sessionId, jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: (queryState) => {
      const status = queryState.state.data?.job.status;
      return status === "queued" || status === "running" ? 1400 : false;
    }
  });
  const job = query.data?.job;
  const cancel = useMutation({
    mutationFn: () => api.cancelJob(sessionId, jobId as string),
    onSuccess: () => query.refetch()
  });
  useEffect(() => {
    if (job?.status === "succeeded" && completedJobId !== job.id) {
      setCompletedJobId(job.id);
      onSucceeded().catch(() => undefined);
    }
  }, [completedJobId, job?.id, job?.status, onSucceeded]);
  return {
    job,
    cancel,
    isActive: job?.status === "queued" || job?.status === "running"
  };
}

function JobProgress({ job, onCancel }: { job: JobRun; onCancel: () => void }) {
  const canCancel = job.status === "queued" || job.status === "running";
  return (
    <div className="border border-awsBorder bg-surface p-4 shadow-console">
      <div className="mb-3 flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-semibold capitalize">{job.operation} job · {job.status.replace("_", " ")}</div>
          <p className="mt-1 text-sm text-awsTextSecondary">{job.message}</p>
        </div>
        {canCancel ? <Button icon={RefreshCw} variant="secondary" onClick={onCancel}>Cancel</Button> : null}
      </div>
      <div className="h-2 w-full border border-awsBorder bg-awsPanelSoft">
        <div className="h-full bg-awsOrange transition-all" style={{ width: `${job.progress}%` }} />
      </div>
      <div className="mt-2 text-xs text-awsTextMuted">
        {job.progress}% complete{job.duration_seconds != null ? ` · ${job.duration_seconds.toFixed(1)}s elapsed` : ""}
      </div>
    </div>
  );
}

function DiagnosticsView({ session, latestExport, setLatestExport }: Parameters<typeof Workspace>[0]) {
  const diagnostics = useQuery({ queryKey: ["diagnostics", session.id], queryFn: () => api.diagnostics(session.id) });
  const liveAgentStatus = useQuery({
    queryKey: ["live-agent-status", session.id, latestExport?.name],
    queryFn: () => api.getLiveAgentStatus(session.id)
  });
  const [jobId, setJobId] = useState<string | null>(null);
  const bundle = latestExport;
  const dossierArtifacts = bundle ? {
    executive: findIncludedArtifact(bundle, "02A-executive-summary.md"),
    full: findIncludedArtifact(bundle, "02B-deep-research-dossier.md"),
    claims: findIncludedArtifact(bundle, "02C-claim-register.md"),
    evidence: findIncludedArtifact(bundle, "02D-evidence-map.md"),
    consistency: findIncludedArtifact(bundle, "02E-consistency-check.md")
  } : null;
  const job = useJobPolling(session.id, jobId, async () => {
    const result = await api.getExport(session.id);
    setLatestExport(result.export);
  });
  const generate = useMutation({ mutationFn: () => api.generateExport(session.id), onSuccess: (result) => setJobId(result.job.id) });
  return (
    <Panel title="Diagnostics" icon={Activity}>
      <div className="mb-4 space-y-3 border border-awsBorder bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="font-semibold">Solution Package Export</div>
            <p className="mt-1 text-sm text-awsTextSecondary">Bundle the brief, report, pricing, architecture, diagrams, evidence, and diagnostics into a local ZIP.</p>
          </div>
          <Button icon={generate.isPending || job.isActive ? Loader2 : Download} disabled={generate.isPending || job.isActive} onClick={() => generate.mutate()}>
            {generate.isPending || job.isActive ? "Exporting" : "Generate Export"}
          </Button>
        </div>
        {job.job ? <JobProgress job={job.job} onCancel={() => job.cancel.mutate()} /> : null}
        {bundle ? (
          <div className="border border-awsBorder bg-white p-3 text-sm">
            <div className="font-semibold">{bundle.name}</div>
            <div className="mt-2 flex flex-wrap gap-2">
              <a href={artifactUrl(session.id, bundle.artifact_id)} className="inline-flex items-center gap-2 border border-awsBorder px-3 py-2 text-awsTextSecondary hover:border-awsOrange">
                <Download className="h-4 w-4" /> Download ZIP
              </a>
              <a href={artifactUrl(session.id, bundle.manifest_artifact_id)} className="inline-flex items-center gap-2 border border-awsBorder px-3 py-2 text-awsTextSecondary hover:border-awsOrange">
                <FileText className="h-4 w-4" /> Manifest
              </a>
            </div>
            {dossierArtifacts ? (
              <div className="mt-3 border-t border-awsBorder pt-3">
                <div className="text-xs font-semibold uppercase text-awsTextMuted">Deep dossier downloads</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {dossierArtifacts.executive ? <DossierLink sessionId={session.id} artifactId={dossierArtifacts.executive} label="Executive summary" /> : null}
                  {dossierArtifacts.full ? <DossierLink sessionId={session.id} artifactId={dossierArtifacts.full} label="Full dossier" /> : null}
                  {dossierArtifacts.claims ? <DossierLink sessionId={session.id} artifactId={dossierArtifacts.claims} label="Claim register" /> : null}
                  {dossierArtifacts.evidence ? <DossierLink sessionId={session.id} artifactId={dossierArtifacts.evidence} label="Evidence map" /> : null}
                  {dossierArtifacts.consistency ? <DossierLink sessionId={session.id} artifactId={dossierArtifacts.consistency} label="Consistency check" /> : null}
                </div>
              </div>
            ) : null}
            {bundle.warnings.length ? <p className="mt-2 text-xs text-awsTextMuted">{bundle.warnings.length} optional artifact warnings included in manifest.</p> : null}
          </div>
        ) : null}
        <LiveAgentStatusCard sessionId={session.id} status={liveAgentStatus.data} bundle={bundle} />
        {generate.error ? <Banner tone="danger" text={(generate.error as Error).message} /> : null}
        {job.job?.status === "failed" ? <Banner tone="danger" text={job.job.error ?? "Export failed. Diagnostics were recorded."} /> : null}
      </div>
      <details className="border border-awsBorder bg-white p-4">
        <summary className="cursor-pointer text-sm font-semibold">Raw diagnostics JSON</summary>
        <pre className="archway-scroll mt-3 max-h-[640px] overflow-auto border border-awsBorder bg-surface p-4 text-xs text-awsTextSecondary">{JSON.stringify(diagnostics.data ?? { loading: true }, null, 2)}</pre>
      </details>
    </Panel>
  );
}

function LiveAgentStatusCard({ sessionId, status, bundle }: { sessionId: string; status?: LiveAgentStatus; bundle: ExportBundle | null }) {
  const rawTrace = bundle ? findIncludedArtifact(bundle, "raw/live_agent_calls.json") : undefined;
  const auditTrace = bundle ? findIncludedArtifact(bundle, "audit_pack/live-agent-calls.md") : undefined;
  const tone = !status || !status.has_export_trace ? "neutral" : status.bedrock_accepted > 0 ? "good" : status.setup_required > 0 ? "warn" : "neutral";
  const toneClass = tone === "good" ? "border-awsSuccess/40 bg-awsSuccess/5" : tone === "warn" ? "border-awsWarning/40 bg-awsWarning/5" : "border-awsBorder bg-white";
  return (
    <div className={`border p-3 text-sm ${toneClass}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 font-semibold"><Bot className="h-4 w-4 text-awsOrange" /> Live Bedrock agent status</div>
          <p className="mt-1 text-sm text-awsTextSecondary">{status?.message ?? "Generate an export to see live-agent audit status."}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs text-awsTextMuted">
          <span className="border border-awsBorder bg-surface px-2 py-1">mode: {status?.agentic_mode ?? "unknown"}</span>
          <span className="border border-awsBorder bg-surface px-2 py-1">provider: {status?.configured_provider ?? "unknown"}</span>
          <span className="border border-awsBorder bg-surface px-2 py-1">model: {status?.configured_model ?? "not configured"}</span>
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-4">
        <LiveMetricPill label="Bedrock accepted" value={status?.bedrock_accepted ?? 0} />
        <LiveMetricPill label="Setup required" value={status?.setup_required ?? 0} />
        <LiveMetricPill label="Skipped" value={status?.skipped ?? 0} />
        <LiveMetricPill label="Failed" value={status?.failed ?? 0} />
      </div>
      {rawTrace || auditTrace ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {rawTrace ? <DossierLink sessionId={sessionId} artifactId={rawTrace} label="Live raw trace" /> : null}
          {auditTrace ? <DossierLink sessionId={sessionId} artifactId={auditTrace} label="Live audit summary" /> : null}
        </div>
      ) : null}
    </div>
  );
}

function LiveMetricPill({ label, value }: { label: string; value: number }) {
  return (
    <div className="border border-awsBorder bg-surface px-3 py-2">
      <div className="text-xs uppercase text-awsTextMuted">{label}</div>
      <div className="mt-1 text-lg font-semibold text-awsTextPrimary">{value}</div>
    </div>
  );
}

function DossierLink({ sessionId, artifactId, label }: { sessionId: string; artifactId: string; label: string }) {
  return (
    <a href={artifactUrl(sessionId, artifactId)} className="inline-flex items-center gap-2 border border-awsBorder px-3 py-2 text-awsTextSecondary hover:border-awsOrange">
      <FileText className="h-4 w-4" /> {label}
    </a>
  );
}

function findIncludedArtifact(bundle: ExportBundle, suffix: string) {
  return bundle.included_artifacts.find((artifact) => artifact.endsWith(suffix));
}

function SolutionBrief({ session, readiness }: { session: Session | null; readiness: Readiness | null }) {
  const brief = session?.current_summary;
  const buildStatus = useQuery({ queryKey: ["build-status"], queryFn: api.buildStatus, refetchInterval: 15000 });
  return (
    <div className="h-full bg-[#eef2f7] p-4">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.14em] text-awsTextMuted"><FileText className="h-4 w-4" /> Live solution brief</h2>
      <BuildStatusCard status={buildStatus.data} />
      {!brief ? <p className="text-sm text-awsTextMuted">Start a session to see the brief evolve.</p> : (
        <div className="space-y-4 text-sm">
          <BriefSection title="Current understanding" items={[brief.refined_problem_statement, brief.industry ? `Industry: ${brief.industry}` : "Industry: worth confirming"]} />
          <BriefSection title="AI behavior" items={brief.ai_capabilities.map((item) => `${item.name} (${item.risk_level})`)} />
          <BriefSection title="Data and integrations" items={[...brief.data_sources.map((item) => `${item.name}: ${item.sensitivity}`), ...brief.integrations.map((item) => `${item.name}: ${item.direction}`)]} />
          <BriefSection title="Assumptions so far" items={brief.assumptions.map((item) => item.text)} />
          <BriefSection title="Worth confirming" items={brief.open_questions.map((item) => item.text)} />
          <div className="border border-awsBorder bg-surface p-3">
            <div className="text-xs uppercase tracking-[0.12em] text-awsTextMuted">Readiness</div>
            <div className="mt-1 text-awsTextPrimary">{readiness?.can_proceed ? "Good enough to proceed" : "Proceed with assumptions"}</div>
          </div>
        </div>
      )}
    </div>
  );
}

function BuildStatusCard({ status }: { status?: BuildStatusSummary }) {
  const items = status?.items ?? [];
  const important = items.filter((item) => item.required || item.status !== "ready").slice(0, 7);
  return (
    <div className="mb-4 border border-awsBorder bg-surface p-3 text-sm">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-xs uppercase tracking-[0.12em] text-awsTextMuted">Build Plumbing</div>
        <StatusPill status={status?.status ?? "degraded"} />
      </div>
      <div className="space-y-2">
        {important.map((item) => (
          <div key={item.id} className="flex items-start gap-2">
            {item.status === "ready" ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-awsSuccess" /> : <TriangleAlert className="mt-0.5 h-4 w-4 text-awsWarning" />}
            <div>
              <div className="text-awsTextPrimary">{item.label}</div>
              <div className="text-xs text-awsTextMuted">{item.status.replace("_", " ")}</div>
            </div>
          </div>
        ))}
        {!important.length ? <p className="text-xs text-awsTextMuted">Loading build status...</p> : null}
      </div>
    </div>
  );
}

function Report({
  session,
  report,
  narrative,
  digest,
  viewModel,
  onReportUpdated,
  onNarrativeUpdated,
  onDigestUpdated,
  onViewModelUpdated,
  onNext
}: {
  session: Session;
  report: ResearchReport;
  narrative: ResearchNarrative | null;
  digest: ResearchDigest | null;
  viewModel: ResearchViewModel | null;
  onReportUpdated: (report: ResearchReport) => void;
  onNarrativeUpdated: (narrative: ResearchNarrative | null) => void;
  onDigestUpdated: (digest: ResearchDigest | null) => void;
  onViewModelUpdated: (viewModel: ResearchViewModel | null) => void;
  onNext: () => void;
}) {
  const [researchSubTab, setResearchSubTab] = useState<"overview" | "architecture" | "pricing" | "competitors" | "risks" | "evidence">("overview");
  const [exportJobId, setExportJobId] = useState<string | null>(null);
  const [researchExport, setResearchExport] = useState<ExportBundle | null>(null);
  const researchQuality = report.metadata?.research_quality as { label?: string; reason?: string } | undefined;
  const evidenceQuality = report.metadata?.evidence_quality as { evidence_authority?: string; limitations?: string[] } | undefined;
  const customerReadiness = report.metadata?.customer_readiness as { status?: string; blockers?: string[]; warnings?: string[] } | undefined;
  const serviceDecisionRecords = (report.metadata?.service_decision_records as Array<{ decision_id?: string; selected_service?: string; capability?: string; required_validation?: string[] }> | undefined) ?? [];
  const serviceValidationNotes = (report.metadata?.service_validation_notes as string[] | undefined) ?? [];
  const competitorStatus = report.metadata?.competitor_scan as Record<string, unknown> | undefined;
  const evidenceById = useMemo(() => Object.fromEntries(report.evidence_items.map((item) => [item.id, item])), [report.evidence_items]);
  const pricingMaturity = String(report.pricing_analysis.metadata?.pricing_maturity ?? "directional");
  const checkpoint = useQuery({ queryKey: ["pricing-checkpoint", session.id, report.pricing_analysis.metadata?.pricing_maturity], queryFn: () => api.getPricingCheckpoint(session.id) });
  const exportJob = useJobPolling(session.id, exportJobId, async () => {
    const result = await api.getExport(session.id);
    setResearchExport(result.export);
  });
  const exportRun = useMutation({ mutationFn: () => api.generateExport(session.id), onSuccess: (result) => setExportJobId(result.job.id) });
  const useProfile = useMutation({
    mutationFn: (profileId: string) => api.usePricingProfile(session.id, profileId),
    onSuccess: async (result) => {
      onReportUpdated(result.report);
      const hydrated = await api.hydrateSession(session.id);
      onNarrativeUpdated(hydrated.research_narrative ?? null);
      onDigestUpdated(hydrated.research_digest ?? null);
      onViewModelUpdated(hydrated.research_view_model ?? null);
    }
  });
  const proceedWithoutHeadline = useMutation({
    mutationFn: () => api.proceedWithoutPricingHeadline(session.id),
    onSuccess: async () => {
      const updated = await api.hydrateSession(session.id);
      onReportUpdated(updated.research ?? report);
      onNarrativeUpdated(updated.research_narrative ?? null);
      onDigestUpdated(updated.research_digest ?? null);
      onViewModelUpdated(updated.research_view_model ?? null);
      onNext();
    }
  });
  if (viewModel) {
    return (
      <div className="space-y-5">
        <ResearchStickyHeader
          sessionId={session.id}
          viewModel={viewModel}
          onNext={onNext}
          onExport={() => exportRun.mutate()}
          exportBusy={exportRun.isPending || exportJob.isActive}
          exportBundle={researchExport}
        />
        {exportJob.job ? <JobProgress job={exportJob.job} onCancel={() => exportJob.cancel.mutate()} /> : null}
        {exportRun.error ? <Banner tone="danger" text={(exportRun.error as Error).message} /> : null}
        <ExecutiveBriefing viewModel={viewModel} />
        <PricingCheckpointCard
          checkpoint={checkpoint.data?.checkpoint}
          loading={checkpoint.isLoading}
          onUseProfile={(profileId) => useProfile.mutate(profileId)}
          onProceedWithoutHeadline={() => proceedWithoutHeadline.mutate()}
          busy={useProfile.isPending || proceedWithoutHeadline.isPending}
        />
        <ResearchSubTabs active={researchSubTab} onChange={setResearchSubTab} />
        {researchSubTab === "overview" ? <OverviewResearchTab viewModel={viewModel} /> : null}
        {researchSubTab === "architecture" ? <ArchitectureRationaleTab viewModel={viewModel} /> : null}
        {researchSubTab === "pricing" ? <PricingResearchTab viewModel={viewModel} /> : null}
        {researchSubTab === "competitors" ? <CompetitorsResearchTab viewModel={viewModel} /> : null}
        {researchSubTab === "risks" ? <RisksResearchTab viewModel={viewModel} /> : null}
        {researchSubTab === "evidence" ? <EvidenceResearchTab viewModel={viewModel} /> : null}
        <TrustPanel pricing={report.pricing_analysis} exportBundle={researchExport} />
        <details className="border border-awsBorder bg-white p-4">
          <summary className="cursor-pointer text-sm font-semibold">Advanced dossier and debug trace</summary>
          <div className="mt-4 space-y-4">
            <NarrativeReport narrative={narrative} report={report} />
            <EvidenceAppendix report={report} />
          </div>
        </details>
      </div>
    );
  }
  return (
    <div className="space-y-5">
      <ResearchDigestDashboard digest={digest} report={report} pricingMaturity={pricingMaturity} />
      <ResearchStatusStrip
        researchQuality={researchQuality}
        evidenceAuthority={titleize(evidenceQuality?.evidence_authority ?? "unknown")}
        citationCoverage={`${report.citation_coverage?.coverage_percent ?? 0}%`}
        customerReadiness={titleize(customerReadiness?.status ?? "unknown")}
      />
      {researchQuality?.reason ? <Banner tone="warning" text={researchQuality.reason} /> : null}
      {customerReadiness?.blockers?.length ? <ListCard title="Customer Readiness Blockers" items={customerReadiness.blockers} /> : null}
      {customerReadiness?.warnings?.length ? <ListCard title="Customer Readiness Warnings" items={customerReadiness.warnings} /> : null}
      <PricingCheckpointCard
        checkpoint={checkpoint.data?.checkpoint}
        loading={checkpoint.isLoading}
        onUseProfile={(profileId) => useProfile.mutate(profileId)}
        onProceedWithoutHeadline={() => proceedWithoutHeadline.mutate()}
        busy={useProfile.isPending || proceedWithoutHeadline.isPending}
      />
      <div className="grid gap-5 2xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-5">
          <details className="border border-awsBorder bg-white p-4">
            <summary className="cursor-pointer text-sm font-semibold">Full dossier detail</summary>
            <div className="mt-4">
              <NarrativeReport narrative={narrative} report={report} />
            </div>
          </details>
          <ServiceRecommendationGrid report={report} evidenceById={evidenceById} />
          <PricingLineGrid report={report} evidenceById={evidenceById} />
        </div>
        <aside className="space-y-4 2xl:sticky 2xl:top-5 2xl:self-start">
          <CompetitorStatusCard status={competitorStatus} fallbackText={report.competitor_analysis} />
          <EvidenceQualityPanel report={report} evidenceById={evidenceById} />
          {serviceValidationNotes.length ? <ListCard title="Validation Notes" items={serviceValidationNotes} /> : null}
          {report.citation_coverage?.warnings.length ? <ListCard title="Citation Notes" items={report.citation_coverage.warnings} /> : null}
        </aside>
      </div>
      {serviceDecisionRecords.length ? (
        <details className="border border-awsBorder bg-surface p-4">
          <summary className="cursor-pointer text-sm font-semibold">Service decision records</summary>
          <div className="mt-3">
            <ListCard
              title="Decision Trace"
              items={serviceDecisionRecords.map((item) => `${item.selected_service} for ${item.capability}${item.required_validation?.length ? ` - ${item.required_validation.length} validation checks` : ""}`)}
            />
          </div>
        </details>
      ) : null}
      <EvidenceAppendix report={report} />
      <Button icon={ChevronRight} onClick={onNext}>Proceed to Architecture</Button>
    </div>
  );
}

function ResearchDigestDashboard({ digest, report, pricingMaturity }: { digest: ResearchDigest | null; report: ResearchReport; pricingMaturity: string }) {
  const safeDigest = digest ?? fallbackDigest(report, pricingMaturity);
  return (
    <section className="border border-awsBorder bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-4xl">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-awsOrange">
            <BookOpen className="h-4 w-4" /> Research digest
          </div>
          <h3 className="text-xl font-semibold leading-8">{safeDigest.headline}</h3>
          <div className="mt-3 flex flex-wrap gap-2">
            <span className="border border-awsBorder bg-white px-3 py-2 text-sm font-semibold">{titleize(safeDigest.decision)}</span>
            <span className="border border-awsBorder bg-white px-3 py-2 text-sm">Pricing: {titleize(pricingMaturity)}</span>
            <span className="border border-awsBorder bg-white px-3 py-2 text-sm">Generated by: {safeDigest.generated_by}</span>
          </div>
        </div>
        <Button icon={ChevronRight} onClick={() => undefined} variant="secondary" className="pointer-events-none opacity-70">Review Summary</Button>
      </div>
      <div className="mt-5 grid gap-4 xl:grid-cols-3">
        <DigestCard title="One-minute read" icon={Gauge} items={safeDigest.one_minute_read} emphasis="primary" />
        <DigestCard title="AWS direction" icon={Layers} items={safeDigest.aws_direction} />
        <DigestCard title="Governance boundaries" icon={ShieldCheck} items={safeDigest.governance_boundaries} emphasis="warning" />
        <DigestCard title="Pricing snapshot" icon={DollarSign} items={[safeDigest.pricing_snapshot, ...safeDigest.pricing_caveats.slice(0, 3)]} emphasis="warning" />
        <DigestCard title="Top risks" icon={AlertTriangle} items={safeDigest.top_risks} emphasis="warning" />
        <DigestCard title="Validate next" icon={ListChecks} items={safeDigest.validate_next} />
      </div>
      {safeDigest.source_chips.length ? (
        <div className="mt-4 border-t border-awsBorder pt-4">
          <div className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-awsTextMuted">Evidence anchors</div>
          <div className="flex flex-wrap gap-2">
            {safeDigest.source_chips.slice(0, 6).map((item) => (
              <span key={`${item.source_type}-${item.title}`} className="max-w-[280px] truncate border border-awsBorder bg-white px-2 py-1 text-xs text-awsTextMuted">
                {item.title} · {item.source_type} · {item.confidence}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {safeDigest.warnings.length ? <p className="mt-3 text-xs text-awsTextMuted">{safeDigest.warnings[0]}</p> : null}
    </section>
  );
}

function DigestCard({
  title,
  icon: Icon,
  items,
  emphasis = "neutral"
}: {
  title: string;
  icon: typeof Activity;
  items: string[];
  emphasis?: "primary" | "warning" | "neutral";
}) {
  const accent = emphasis === "primary" ? "border-l-awsOrange" : emphasis === "warning" ? "border-l-awsWarning" : "border-l-awsInfo";
  return (
    <div className={`min-h-48 border border-l-4 border-awsBorder ${accent} bg-white p-4`}>
      <div className="mb-3 flex items-center gap-2 font-semibold"><Icon className="h-4 w-4 text-awsOrange" /> {title}</div>
      <ul className="space-y-2 text-sm leading-6 text-awsTextSecondary">
        {items.slice(0, 5).map((item) => <li key={item}>{item}</li>)}
      </ul>
    </div>
  );
}

function fallbackDigest(report: ResearchReport, pricingMaturity: string): ResearchDigest {
  return {
    headline: report.executive_verdict.split(". ")[0],
    decision: titleize(report.proceed_recommendation),
    one_minute_read: [report.use_case_interpretation.split(". ")[0], `Customer posture: ${titleize(String(report.metadata?.customer_readiness ? (report.metadata.customer_readiness as { status?: string }).status ?? "unknown" : "unknown"))}`],
    aws_direction: [report.recommended_poc, report.recommended_production_direction].map((item) => item.split(". ")[0]),
    governance_boundaries: ["Approval gates required for high-impact writes.", "Audit trail and rollback controls remain mandatory."],
    pricing_snapshot: `Directional pricing only. Maturity: ${titleize(pricingMaturity)}.`,
    pricing_caveats: report.pricing_analysis.unknown_variables.slice(0, 3),
    top_risks: report.risks.slice(0, 4).map((item) => `${item.severity}: ${item.title}`),
    validate_next: report.pricing_analysis.unknown_variables.slice(0, 4),
    source_chips: report.evidence_items.slice(0, 6).map((item) => ({ title: item.title, source_type: item.source_type, confidence: item.confidence })),
    generated_by: "deterministic",
    warnings: []
  };
}

function ResearchStickyHeader({
  sessionId,
  viewModel,
  onNext,
  onExport,
  exportBusy,
  exportBundle
}: {
  sessionId: string;
  viewModel: ResearchViewModel;
  onNext: () => void;
  onExport: () => void;
  exportBusy: boolean;
  exportBundle: ExportBundle | null;
}) {
  return (
    <div className="sticky top-0 z-20 border border-awsBorder bg-white/95 p-3 shadow-console backdrop-blur">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap gap-2">
            <ResearchBadge badge={viewModel.verdict} />
            <ResearchBadge badge={viewModel.readiness} />
            <ResearchBadge badge={viewModel.pricing_confidence} />
            <ResearchBadge badge={viewModel.evidence_quality} />
            <ResearchBadge badge={viewModel.competitor_scan_status} />
          </div>
          <p className="mt-2 truncate text-sm font-medium text-awsTextPrimary" title={viewModel.executive_briefing.headline}>{viewModel.executive_briefing.headline}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button icon={ChevronRight} onClick={onNext}>Review Summary</Button>
          <Button icon={exportBusy ? Loader2 : Download} variant="secondary" disabled={exportBusy} onClick={onExport}>{exportBusy ? "Exporting" : "Export"}</Button>
          {exportBundle ? (
            <a href={artifactUrl(sessionId, exportBundle.artifact_id)} className="inline-flex min-h-10 items-center justify-center gap-2 border border-awsBorder bg-awsPanelSoft px-3 py-2 text-sm font-semibold text-awsTextPrimary hover:border-awsOrange">
              <Download className="h-4 w-4" /> ZIP ready
            </a>
          ) : null}
          <Button icon={RefreshCw} variant="secondary" disabled title="Refresh evidence requires a fresh research run so citations, pricing, and competitor context stay consistent.">Refresh evidence</Button>
          <Button icon={Search} variant="secondary" disabled title="Competitor scan runs during a fresh research pass when Tavily is enabled.">Run competitor scan</Button>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-awsTextMuted">
        <span>Model: {viewModel.model}</span>
        <span>Last refreshed: {new Date(viewModel.generated_at).toLocaleString()}</span>
      </div>
    </div>
  );
}

function ResearchBadge({ badge }: { badge: ResearchViewModel["verdict"] }) {
  const tone = badge.tone === "success" ? "border-awsSuccess/50 text-awsSuccess bg-[#f1f8f5]" : badge.tone === "danger" ? "border-awsDanger/50 text-awsDanger bg-[#fff1f2]" : badge.tone === "warning" ? "border-awsOrange/50 text-awsTextPrimary bg-[#fff8eb]" : "border-awsBorder text-awsTextSecondary bg-white";
  return <span className={`inline-flex items-center gap-1 border px-2 py-1 text-xs ${tone}`}><span className="text-awsTextMuted">{badge.label}:</span> <span className="font-semibold">{badge.value}</span></span>;
}

function ExecutiveBriefing({ viewModel }: { viewModel: ResearchViewModel }) {
  const executive = viewModel.executive_briefing;
  return (
    <section className="border border-awsBorder bg-surface p-5">
      <div className="mb-4">
        <div className="text-xs font-semibold uppercase tracking-[0.14em] text-awsOrange">Executive briefing</div>
        <h3 className="mt-2 text-xl font-semibold leading-8">{executive.headline}</h3>
      </div>
      <div className="grid gap-4 xl:grid-cols-5">
        <BriefingCard title="One-minute read" icon={Gauge} items={executive.one_minute_read} emphasis="primary" />
        <BriefingCard title="AWS direction" icon={Layers} items={executive.aws_direction} />
        <BriefingCard title="Governance boundary" icon={ShieldCheck} items={executive.governance_boundary} emphasis="warning" />
        <BriefingCard title="Top risks" icon={AlertTriangle} items={executive.top_risks} emphasis="warning" />
        <BriefingCard title="Validate next" icon={ListChecks} items={executive.validate_next} />
      </div>
    </section>
  );
}

function BriefingCard({ title, icon: Icon, items, emphasis = "neutral" }: { title: string; icon: typeof Activity; items: string[]; emphasis?: "primary" | "warning" | "neutral" }) {
  const accent = emphasis === "primary" ? "border-t-awsOrange" : emphasis === "warning" ? "border-t-awsWarning" : "border-t-awsInfo";
  return (
    <div className={`border border-t-4 border-awsBorder ${accent} bg-white p-4`}>
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><Icon className="h-4 w-4 text-awsOrange" /> {title}</div>
      <ul className="space-y-2 text-sm leading-6 text-awsTextSecondary">
        {items.slice(0, 5).map((item) => <li key={item}>{item}</li>)}
      </ul>
    </div>
  );
}

function ResearchSubTabs({ active, onChange }: { active: string; onChange: (tab: "overview" | "architecture" | "pricing" | "competitors" | "risks" | "evidence") => void }) {
  const tabs: Array<["overview" | "architecture" | "pricing" | "competitors" | "risks" | "evidence", string, typeof Activity]> = [
    ["overview", "Overview", BookOpen],
    ["architecture", "Architecture rationale", Layers],
    ["pricing", "Pricing", DollarSign],
    ["competitors", "Competitors", Search],
    ["risks", "Risks & validation", AlertTriangle],
    ["evidence", "Evidence", ShieldCheck],
  ];
  return (
    <div className="sticky top-[104px] z-10 flex flex-wrap gap-1 border border-awsBorder bg-white p-2 shadow-console">
      {tabs.map(([id, label, Icon]) => (
        <button key={id} onClick={() => onChange(id)} className={`flex items-center gap-2 border px-3 py-2 text-sm ${active === id ? "border-awsOrange bg-awsPanelSoft text-awsTextPrimary" : "border-transparent text-awsTextMuted hover:border-awsBorder"}`}>
          <Icon className="h-4 w-4" /> {label}
        </button>
      ))}
    </div>
  );
}

function OverviewResearchTab({ viewModel }: { viewModel: ResearchViewModel }) {
  const overview = viewModel.overview;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <BriefingCard title="Use-case interpretation" icon={BookOpen} items={overview.use_case_interpretation} emphasis="primary" />
      <BriefingCard title="What Archway understood" icon={Gauge} items={overview.understood} />
      <BriefingCard title="Confirmed" icon={CheckCircle2} items={overview.confirmed} />
      <BriefingCard title="Assumed" icon={AlertTriangle} items={overview.assumed} emphasis="warning" />
      <BriefingCard title="Open" icon={ListChecks} items={overview.open_items} emphasis="warning" />
      <div className="grid gap-4 md:grid-cols-2 xl:col-span-2">
        <BriefingCard title="Recommended POC path" icon={Sparkles} items={overview.poc_path} emphasis="primary" />
        <BriefingCard title="Recommended Production path" icon={ShieldCheck} items={overview.production_path} />
      </div>
    </div>
  );
}

function ArchitectureRationaleTab({ viewModel }: { viewModel: ResearchViewModel }) {
  const architecture = viewModel.architecture_rationale;
  const grouped = architecture.service_groups.reduce<Record<string, typeof architecture.service_groups>>((acc, item) => {
    acc[item.group] = [...(acc[item.group] ?? []), item];
    return acc;
  }, {});
  return (
    <div className="space-y-4">
      <div className="border border-awsBorder bg-surface p-4">
        <div className="text-sm font-semibold">Architecture pattern</div>
        <p className="mt-2 text-sm leading-6 text-awsTextSecondary">{architecture.pattern}</p>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <BriefingCard title="POC recommendation" icon={Sparkles} items={architecture.poc_recommendation} />
        <BriefingCard title="Production recommendation" icon={ShieldCheck} items={architecture.production_recommendation} />
      </div>
      {Object.entries(grouped).map(([group, services]) => (
        <section key={group} className="border border-awsBorder bg-surface p-4">
          <h3 className="mb-3 font-semibold">{group}</h3>
          <div className="grid gap-3 xl:grid-cols-2">
            {services.map((item) => <ServiceRationaleCard key={`${group}-${item.service}-${item.role}`} item={item} />)}
          </div>
        </section>
      ))}
      <div className="grid gap-4 xl:grid-cols-2">
        <BriefingCard title="Alternatives and trade-offs" icon={LayoutDashboard} items={architecture.tradeoffs} />
        <BriefingCard title="What not to build first" icon={TriangleAlert} items={architecture.do_not_build_first} emphasis="warning" />
      </div>
    </div>
  );
}

function ServiceRationaleCard({ item }: { item: ResearchViewModel["architecture_rationale"]["service_groups"][number] }) {
  return (
    <details className="border border-awsBorder bg-white p-4">
      <summary className="cursor-pointer font-semibold">{item.service}</summary>
      <div className="mt-3 space-y-3 text-sm leading-6 text-awsTextSecondary">
        <p><span className="font-semibold text-awsTextPrimary">Role:</span> {item.role}</p>
        <p><span className="font-semibold text-awsTextPrimary">Why selected:</span> {item.why_selected}</p>
        {item.alternatives.length ? <p><span className="font-semibold text-awsTextPrimary">Alternatives:</span> {item.alternatives.join(", ")}</p> : null}
        <p><span className="font-semibold text-awsTextPrimary">Validation:</span> {item.validation_needed}</p>
        <p><span className="font-semibold text-awsTextPrimary">Evidence:</span> {item.evidence_summary}</p>
      </div>
    </details>
  );
}

function PricingResearchTab({ viewModel }: { viewModel: ResearchViewModel }) {
  const [phase, setPhase] = useState<"poc" | "production">("poc");
  const pricing = phase === "poc" ? viewModel.pricing_poc : viewModel.pricing_production;
  return (
    <div className="space-y-4">
      <div className="inline-flex border border-awsBorder bg-white p-1">
        {(["poc", "production"] as const).map((id) => <button key={id} onClick={() => setPhase(id)} className={`px-3 py-2 text-sm font-semibold ${phase === id ? "bg-awsPanelSoft text-awsTextPrimary" : "text-awsTextMuted"}`}>{id.toUpperCase()} pricing</button>)}
      </div>
      <PricingSummary pricing={pricing} />
      <PricingAssumptionsTable pricing={pricing} />
      <PricingBreakdownTable pricing={pricing} />
      <div className="grid gap-4 xl:grid-cols-2">
        <BriefingCard title="Pricing exclusions" icon={Lock} items={pricing.excluded_costs} emphasis="warning" />
        <BriefingCard title="Pricing readiness" icon={ListChecks} items={pricing.readiness_findings} emphasis={pricing.procurement_ready ? "primary" : "warning"} />
      </div>
    </div>
  );
}

function PricingSummary({ pricing }: { pricing: PricingViewModel }) {
  return (
    <section className="border border-awsBorder bg-surface p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">{pricing.phase.toUpperCase()} pricing summary</h3>
          {!pricing.procurement_ready ? <p className="mt-1 text-sm text-awsTextMuted">Directional estimate only. Not procurement-ready.</p> : null}
        </div>
        <StatusPill status={pricing.procurement_ready ? "ready" : "degraded"} />
      </div>
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Metric label="Monthly range" value={`${pricing.monthly_low} / ${pricing.monthly_high}`} />
        <Metric label="Expected" value={pricing.monthly_expected} />
        <Metric label="Confidence" value={pricing.confidence} />
        <Metric label="SKU-backed" value={pricing.sku_backed_subtotal} />
        <Metric label="Directional" value={pricing.directional_subtotal} />
        <Metric label="Heuristic" value={pricing.heuristic_subtotal} />
      </div>
      <p className="mt-3 text-xs text-awsTextMuted">Last pricing refresh: {new Date(pricing.last_refreshed).toLocaleString()}</p>
    </section>
  );
}

function PricingAssumptionsTable({ pricing }: { pricing: PricingViewModel }) {
  return <Table headers={["Assumption", "Value", "Unit", "Source", "Confidence", "Used by", "Notes"]} rows={pricing.assumptions.map((item) => [item.assumption, item.value, item.unit, item.source, item.confidence, item.used_by, item.notes])} />;
}

function PricingBreakdownTable({ pricing }: { pricing: PricingViewModel }) {
  return (
    <div className="space-y-2">
      <Table headers={["AWS service", "Architecture role", "Cost category", "Quantity", "Unit", "Rate", "Monthly subtotal", "Pricing basis", "Confidence"]} rows={pricing.line_items.map((item) => [item.service, item.architecture_role, item.cost_category, item.quantity, item.unit, item.rate, item.monthly_subtotal, item.pricing_basis, item.confidence])} />
      <details className="border border-awsBorder bg-white p-4">
        <summary className="cursor-pointer text-sm font-semibold">Expand SKU/rate trace</summary>
        <div className="mt-3 space-y-3">
          {pricing.line_items.map((item) => (
            <div key={`${item.service}-${item.monthly_subtotal}`} className="border border-awsBorder bg-surface p-3 text-sm">
              <div className="font-semibold">{item.service}: {item.trace_summary}</div>
              <pre className="archway-scroll mt-2 max-h-48 overflow-auto bg-white p-3 text-xs text-awsTextMuted">{JSON.stringify(item.trace, null, 2)}</pre>
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}

function CompetitorsResearchTab({ viewModel }: { viewModel: ResearchViewModel }) {
  const scan = viewModel.competitor_scan;
  const disabledReason = !scan.tavily_enabled
    ? "Tavily is not enabled for this session."
    : !scan.scan_enabled
      ? "Competitor scan is not enabled for this session."
      : "Run a fresh research pass to refresh competitor analysis.";
  return (
    <div className="space-y-4">
      <section className="border border-awsBorder bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="font-semibold">Competitor scan: {scan.status.replace("_", " ")}</h3>
            <p className="mt-1 text-sm text-awsTextMuted">{scan.failure_reason || scan.skipped_reason || "Competitor context is shown only when external evidence is available."}</p>
          </div>
          <Button icon={Search} variant="secondary" disabled title={disabledReason}>Run with research</Button>
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-3 xl:grid-cols-6">
          <Metric label="Tavily" value={String(scan.tavily_enabled)} />
          <Metric label="Scan enabled" value={String(scan.scan_enabled)} />
          <Metric label="Budget" value={String(scan.budget)} />
          <Metric label="Attempted" value={String(scan.queries_attempted)} />
          <Metric label="Executed" value={String(scan.queries_executed)} />
          <Metric label="Returned" value={String(scan.results_returned)} />
          <Metric label="Used" value={String(scan.results_used)} />
        </div>
      </section>
      {scan.analysis_summary.length || scan.aws_positioning_implications.length ? (
        <div className="grid gap-4 xl:grid-cols-2">
          <BriefingCard title="Market signals" icon={Search} items={scan.analysis_summary.length ? scan.analysis_summary : ["No market signals were returned by Tavily."]} />
          <BriefingCard title="AWS positioning implication" icon={ShieldCheck} items={scan.aws_positioning_implications.length ? scan.aws_positioning_implications : ["Use competitor evidence as context only; AWS architecture decisions remain governed by requirements, evidence, and pricing readiness."]} emphasis="primary" />
        </div>
      ) : null}
      {scan.query_plan.length ? (
        <details className="border border-awsBorder bg-white p-4">
          <summary className="cursor-pointer text-sm font-semibold">Tavily query plan</summary>
          <ul className="mt-3 space-y-2 text-sm leading-6 text-awsTextSecondary">
            {scan.query_plan.map((query) => <li key={query}>{query}</li>)}
          </ul>
        </details>
      ) : null}
      {scan.competitors.length ? (
        <div className="grid gap-4 xl:grid-cols-2">
          {scan.competitors.map((item) => (
            <div key={item.name} className="border border-awsBorder bg-white p-4">
              <h4 className="font-semibold">{item.name}</h4>
              <p className="mt-1 text-sm text-awsTextMuted">{item.type} · {item.relevance}</p>
              <p className="mt-3 text-sm leading-6 text-awsTextSecondary">{item.impact}</p>
              {item.strengths.length ? (
                <div className="mt-3">
                  <div className="text-xs font-semibold uppercase tracking-[0.12em] text-awsTextMuted">Observed signals</div>
                  <ul className="mt-2 space-y-1 text-sm leading-6 text-awsTextSecondary">
                    {item.strengths.slice(0, 3).map((signal) => <li key={signal}>{signal}</li>)}
                  </ul>
                </div>
              ) : null}
              <SourceChips labels={[item.source]} />
            </div>
          ))}
        </div>
      ) : <Banner tone="warning" text={scan.failure_reason || scan.skipped_reason || "Competitor scan was not run for this session."} />}
    </div>
  );
}

function RisksResearchTab({ viewModel }: { viewModel: ResearchViewModel }) {
  const grouped = viewModel.risks.reduce<Record<string, typeof viewModel.risks>>((acc, item) => {
    acc[item.group] = [...(acc[item.group] ?? []), item];
    return acc;
  }, {});
  return (
    <div className="space-y-4">
      {Object.entries(grouped).map(([group, risks]) => (
        <section key={group} className="border border-awsBorder bg-surface p-4">
          <h3 className="mb-3 font-semibold">{group}</h3>
          <div className="grid gap-3 xl:grid-cols-2">
            {risks.map((risk) => (
              <div key={`${group}-${risk.title}`} className="border border-awsBorder bg-white p-4">
                <div className="flex items-center justify-between gap-2">
                  <h4 className="font-semibold">{risk.title}</h4>
                  <span className="border border-awsOrange/50 px-2 py-1 text-xs text-awsOrange">{risk.severity}</span>
                </div>
                <p className="mt-2 text-sm leading-6 text-awsTextSecondary">{risk.why_it_matters}</p>
                <p className="mt-2 text-sm leading-6 text-awsTextSecondary"><span className="font-semibold text-awsTextPrimary">Mitigation:</span> {risk.mitigation}</p>
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-awsTextMuted">
                  <span>Owner: {risk.validation_owner}</span>
                  <span>Blocks procurement: {risk.blocks_procurement ? "yes" : "no"}</span>
                  <span>Blocks final diagrams: {risk.blocks_diagram_finalization ? "yes" : "no"}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function EvidenceResearchTab({ viewModel }: { viewModel: ResearchViewModel }) {
  const evidence = viewModel.evidence_summary;
  return (
    <div className="space-y-4">
      <section className="border border-awsBorder bg-surface p-4">
        <div className="grid gap-3 md:grid-cols-4">
          <Metric label="Authority" value={evidence.evidence_authority} />
          <Metric label="Claim coverage" value={evidence.claim_coverage} />
          <Metric label="Source types" value={String(Object.keys(evidence.source_counts).length)} />
          <Metric label="Refreshed" value={new Date(evidence.last_refreshed).toLocaleDateString()} />
        </div>
      </section>
      <section className="border border-awsBorder bg-surface p-4">
        <h3 className="mb-3 font-semibold">Top sources</h3>
        <div className="grid gap-3 xl:grid-cols-2">
          {evidence.top_sources.map((item) => (
            <div key={`${item.source_type}-${item.title}`} className="border border-awsBorder bg-white p-4">
              <h4 className="font-semibold">{item.title}</h4>
              <p className="mt-1 text-sm text-awsTextMuted">{item.source_type} · {item.confidence} · used for {item.used_for}</p>
              {item.url ? <a href={item.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex text-sm text-awsOrange">Open source</a> : null}
            </div>
          ))}
        </div>
      </section>
      <details className="border border-awsBorder bg-white p-4">
        <summary className="cursor-pointer text-sm font-semibold">Advanced evidence IDs</summary>
        <Table headers={["Source title", "Type", "Confidence", "Used for", "Debug ID"]} rows={evidence.evidence_items_for_debug.map((item) => [item.title, item.source_type, item.confidence, item.used_for, item.debug_id ?? ""])} />
      </details>
    </div>
  );
}

function ResearchHero({ report, pricingMaturity }: { report: ResearchReport; pricingMaturity: string }) {
  return (
    <div className="border border-awsBorder bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-4xl">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-awsOrange">
            <BookOpen className="h-4 w-4" /> Research dossier
          </div>
          <h3 className="text-xl font-semibold leading-8">{report.executive_verdict}</h3>
          <p className="mt-3 text-sm leading-6 text-awsTextSecondary">{report.use_case_interpretation}</p>
        </div>
        <div className="grid min-w-[260px] gap-2 text-sm">
          <StatusLine label="Recommendation" value={titleize(report.proceed_recommendation)} />
          <StatusLine label="Pricing maturity" value={titleize(pricingMaturity)} />
          <StatusLine label="Region" value={report.pricing_analysis.region} />
        </div>
      </div>
    </div>
  );
}

function ResearchStatusStrip({
  researchQuality,
  evidenceAuthority,
  citationCoverage,
  customerReadiness
}: {
  researchQuality?: { label?: string };
  evidenceAuthority: string;
  citationCoverage: string;
  customerReadiness: string;
}) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <StatusMetric icon={Gauge} label="Research quality" value={researchQuality?.label ?? "Unknown"} />
      <StatusMetric icon={ShieldCheck} label="Evidence authority" value={evidenceAuthority} />
      <StatusMetric icon={ListChecks} label="Citation coverage" value={citationCoverage} />
      <StatusMetric icon={CheckCircle2} label="Customer readiness" value={customerReadiness} />
    </div>
  );
}

function StatusMetric({ icon: Icon, label, value }: { icon: typeof Activity; label: string; value: string }) {
  return (
    <div className="border border-awsBorder bg-white p-4">
      <div className="flex items-center gap-2 text-xs uppercase tracking-[0.12em] text-awsTextMuted"><Icon className="h-4 w-4 text-awsOrange" /> {label}</div>
      <div className="mt-2 text-lg font-semibold">{value}</div>
    </div>
  );
}

function StatusLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 border border-awsBorder bg-white px-3 py-2">
      <span className="text-awsTextMuted">{label}</span>
      <span className="font-semibold">{value}</span>
    </div>
  );
}

function NarrativeReport({ narrative, report }: { narrative: ResearchNarrative | null; report: ResearchReport }) {
  if (!narrative?.sections?.length) {
    return (
      <div className="grid gap-4 xl:grid-cols-2">
        <ResearchSectionCard
          title="Recommended AWS direction"
          icon={Layers}
          emphasis="primary"
          markdown={`### Production direction\n${report.recommended_production_direction}\n\n### POC scope\n${report.recommended_poc}`}
        />
        <ResearchSectionCard
          title="Risks and assumptions"
          icon={AlertTriangle}
          emphasis="warning"
          markdown={report.risks.map((item) => `- **${item.severity}**: ${item.title} - ${item.mitigation}`).join("\n")}
        />
      </div>
    );
  }
  const priority = ["executive_verdict", "use_case_interpretation", "architecture_recommendation", "service_decision_matrix", "pricing_analysis", "validation_plan"];
  const primarySections = narrative.sections.filter((section) => priority.includes(section.id));
  const secondarySections = narrative.sections.filter((section) => !priority.includes(section.id) && section.id !== "evidence_appendix");
  const evidenceSection = narrative.sections.find((section) => section.id === "evidence_appendix");
  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-2">
        {primarySections.map((section) => (
          <ResearchSectionCard key={section.id} {...sectionMeta(section.id, section.title)} markdown={section.markdown} />
        ))}
      </div>
      {secondarySections.length ? (
        <details className="border border-awsBorder bg-white p-4">
          <summary className="cursor-pointer text-sm font-semibold">More research detail and trade-offs</summary>
          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            {secondarySections.map((section) => (
              <ResearchSectionCard key={section.id} {...sectionMeta(section.id, section.title)} markdown={section.markdown} compact />
            ))}
          </div>
        </details>
      ) : null}
      {evidenceSection ? (
        <details className="border border-awsBorder bg-white p-4">
          <summary className="cursor-pointer text-sm font-semibold">Evidence narrative</summary>
          <div className="mt-4">
            <MarkdownBlock markdown={hideEvidenceIds(evidenceSection.markdown)} unframed />
          </div>
        </details>
      ) : null}
    </div>
  );
}

function ResearchSectionCard({
  title,
  icon: Icon,
  markdown,
  emphasis = "neutral",
  compact = false
}: {
  title: string;
  icon: typeof Activity;
  markdown: string;
  emphasis?: "primary" | "warning" | "neutral";
  compact?: boolean;
}) {
  const accent = emphasis === "primary" ? "border-l-awsOrange" : emphasis === "warning" ? "border-l-awsWarning" : "border-l-awsInfo";
  return (
    <section className={`border border-l-4 border-awsBorder ${accent} bg-white p-4`}>
      <div className="mb-3 flex items-center gap-2">
        <Icon className="h-4 w-4 text-awsOrange" />
        <h3 className="text-base font-semibold">{title}</h3>
      </div>
      <div className={compact ? "max-h-80 overflow-y-auto pr-2" : ""}>
        <MarkdownBlock markdown={hideEvidenceIds(markdown)} unframed />
      </div>
    </section>
  );
}

function sectionMeta(id: string, fallbackTitle: string): { title: string; icon: typeof Activity; emphasis?: "primary" | "warning" | "neutral" } {
  const meta: Record<string, { title: string; icon: typeof Activity; emphasis?: "primary" | "warning" | "neutral" }> = {
    executive_verdict: { title: "Executive verdict", icon: Gauge, emphasis: "primary" },
    use_case_interpretation: { title: "Use-case interpretation", icon: BookOpen },
    architecture_recommendation: { title: "Recommended AWS direction", icon: Layers, emphasis: "primary" },
    service_decision_matrix: { title: "Service selection rationale", icon: Database },
    pricing_analysis: { title: "Pricing direction and drivers", icon: DollarSign, emphasis: "warning" },
    validation_plan: { title: "Validation gates", icon: ListChecks, emphasis: "warning" },
    technical_feasibility: { title: "Alternatives and trade-offs", icon: LayoutDashboard },
    competitive_landscape: { title: "Competitor / market scan", icon: Search },
    risk_matrix: { title: "Risks and assumptions", icon: AlertTriangle, emphasis: "warning" },
    security_compliance: { title: "Security and compliance", icon: ShieldCheck, emphasis: "primary" },
    reliability_resilience: { title: "Reliability and resilience", icon: Activity },
    performance_scalability: { title: "Performance and scalability", icon: Gauge },
  };
  return meta[id] ?? { title: fallbackTitle, icon: FileText };
}

function CompetitorStatusCard({ status, fallbackText }: { status?: Record<string, unknown>; fallbackText: string }) {
  const rows = status ? [
    ["Tavily enabled", boolLabel(status.tavily_enabled)],
    ["Competitor scan enabled", boolLabel(status.competitor_scan_enabled)],
    ["Session budget", String(status.session_budget ?? "unknown")],
    ["Queries executed", String(status.queries_executed ?? 0)],
    ["Results returned", String(status.results_returned ?? 0)],
    ["Results used", String(status.results_used ?? 0)],
  ] : [];
  return (
    <div className="border border-awsBorder bg-surface p-4">
      <div className="mb-3 flex items-center gap-2 font-semibold"><Search className="h-4 w-4 text-awsOrange" /> Competitor / Market Scan</div>
      {rows.length ? <Table headers={["Signal", "Value"]} rows={rows} /> : <MarkdownBlock markdown={hideEvidenceIds(fallbackText)} />}
      {status?.skipped_reason ? <Banner tone="warning" text={String(status.skipped_reason)} /> : null}
      {status?.failure_reason ? <Banner tone="danger" text={String(status.failure_reason)} /> : null}
    </div>
  );
}

function ServiceRecommendationGrid({
  report,
  evidenceById
}: {
  report: ResearchReport;
  evidenceById: Record<string, ResearchReport["evidence_items"][number]>;
}) {
  return (
    <section className="border border-awsBorder bg-surface p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 font-semibold"><Database className="h-4 w-4 text-awsOrange" /> AWS service choices</div>
          <p className="mt-1 text-sm text-awsTextMuted">Selected services, rationale, and readable source anchors.</p>
        </div>
        <span className="border border-awsBorder bg-white px-2 py-1 text-xs text-awsTextMuted">{report.aws_service_recommendations.length} services</span>
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        {report.aws_service_recommendations.map((item) => (
          <div key={`${item.service}-${item.purpose}`} className="border border-awsBorder bg-white p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h4 className="font-semibold">{item.service}</h4>
                <p className="mt-1 text-sm text-awsTextMuted">{item.purpose}</p>
              </div>
            </div>
            <p className="mt-3 text-sm leading-6 text-awsTextSecondary">{item.rationale}</p>
            <SourceChips labels={evidenceLabels(item.evidence_ids, evidenceById)} />
            {item.alternatives_considered.length ? (
              <p className="mt-3 text-xs text-awsTextMuted">Alternatives considered: {item.alternatives_considered.join(", ")}</p>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function PricingLineGrid({
  report,
  evidenceById
}: {
  report: ResearchReport;
  evidenceById: Record<string, ResearchReport["evidence_items"][number]>;
}) {
  return (
    <section className="border border-awsBorder bg-surface p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 font-semibold"><DollarSign className="h-4 w-4 text-awsOrange" /> Pricing model</div>
          <p className="mt-1 text-sm text-awsTextMuted">Directional cost drivers and evidence anchors, not procurement-ready SKU math unless marked.</p>
        </div>
        <div className="flex flex-wrap gap-2 text-sm">
          <span className="border border-awsBorder bg-white px-3 py-2">Expected ${report.pricing_analysis.expected_monthly_usd}</span>
          <span className="border border-awsBorder bg-white px-3 py-2">Range ${report.pricing_analysis.low_monthly_usd}-${report.pricing_analysis.high_monthly_usd}</span>
        </div>
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        {report.pricing_analysis.line_items.map((item) => (
          <div key={`${item.service}-${item.unit_basis}`} className="border border-awsBorder bg-white p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h4 className="font-semibold">{item.service}</h4>
                <p className="mt-1 text-sm text-awsTextMuted">{item.unit_basis}</p>
              </div>
              <span className="border border-awsOrange/50 px-2 py-1 text-sm font-semibold text-awsOrange">${item.expected_monthly_usd}</span>
            </div>
            {item.assumptions?.length ? <p className="mt-3 text-sm leading-6 text-awsTextSecondary">{item.assumptions.slice(0, 2).join(" ")}</p> : null}
            <SourceChips labels={evidenceLabels(item.evidence_ids, evidenceById)} fallback="Assumption-backed" />
          </div>
        ))}
      </div>
      {report.pricing_analysis.main_cost_drivers.length ? (
        <div className="mt-4 border border-awsBorder bg-white p-4">
          <div className="mb-2 text-sm font-semibold">Main cost drivers</div>
          <ul className="grid gap-2 text-sm text-awsTextSecondary md:grid-cols-2">
            {report.pricing_analysis.main_cost_drivers.slice(0, 8).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function EvidenceQualityPanel({
  report,
  evidenceById
}: {
  report: ResearchReport;
  evidenceById: Record<string, ResearchReport["evidence_items"][number]>;
}) {
  const bySource = report.evidence_items.reduce<Record<string, number>>((acc, item) => {
    acc[item.source_type] = (acc[item.source_type] ?? 0) + 1;
    return acc;
  }, {});
  const trusted = report.evidence_assessments.slice(0, 5).map((item) => {
    const evidence = evidenceById[item.evidence_id];
    return `${evidence?.title ?? "Evidence item"}: ${item.trust_label}`;
  });
  return (
    <div className="border border-awsBorder bg-surface p-4">
      <div className="mb-3 flex items-center gap-2 font-semibold"><ShieldCheck className="h-4 w-4 text-awsOrange" /> Evidence quality</div>
      <div className="grid grid-cols-2 gap-2">
        {Object.entries(bySource).map(([source, count]) => (
          <div key={source} className="border border-awsBorder bg-white p-3">
            <div className="text-xs uppercase text-awsTextMuted">{source}</div>
            <div className="mt-1 text-xl font-semibold">{count}</div>
          </div>
        ))}
      </div>
      {trusted.length ? (
        <div className="mt-3 border-t border-awsBorder pt-3">
          <div className="mb-2 text-sm font-semibold">Top source checks</div>
          <ul className="space-y-2 text-sm leading-6 text-awsTextSecondary">
            {trusted.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function SourceChips({ labels, fallback = "No source title captured" }: { labels: string[]; fallback?: string }) {
  const visible = labels.slice(0, 3);
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {(visible.length ? visible : [fallback]).map((label) => (
        <span key={label} className="max-w-full truncate border border-awsBorder bg-awsPanelSoft px-2 py-1 text-xs text-awsTextMuted">
          {label}
        </span>
      ))}
      {labels.length > visible.length ? <span className="border border-awsBorder bg-white px-2 py-1 text-xs text-awsTextMuted">+{labels.length - visible.length} more</span> : null}
    </div>
  );
}

function EvidenceAppendix({ report }: { report: ResearchReport }) {
  return (
    <details className="border border-awsBorder bg-surface p-4">
      <summary className="cursor-pointer text-sm font-semibold">Evidence appendix and debug identifiers</summary>
      <p className="mt-2 text-sm text-awsTextMuted">Raw evidence IDs are available here for audit/debug use only.</p>
      <Table rows={report.evidence_items.map((item) => [item.title, item.source_type, item.confidence, item.id])} headers={["Source title", "Source", "Confidence", "Debug ID"]} />
    </details>
  );
}

function evidenceLabels(ids: string[], evidenceById: Record<string, ResearchReport["evidence_items"][number]>) {
  return ids.map((id) => evidenceById[id]?.title).filter(Boolean);
}

function boolLabel(value: unknown) {
  return value === true ? "true" : value === false ? "false" : "unknown";
}

function hideEvidenceIds(value: string) {
  return value.replace(/\bev_[a-f0-9]{10}\b/g, "source");
}

function titleize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char: string) => char.toUpperCase());
}

function interviewTurnCount(session: Session) {
  const profile = session.current_summary?.use_case_profile as { interview?: { turn_count?: number; answered?: string[] } } | undefined;
  return profile?.interview?.turn_count ?? profile?.interview?.answered?.length ?? 0;
}

function interviewPromptFromReadiness(readiness: Readiness | null) {
  const question = readiness?.recommended_minimum_questions?.[0];
  if (!question) {
    return "I have enough to shape the first research pass. Add any constraints you want captured before research, or proceed when ready.";
  }
  return [
    "Let’s tighten the brief before research.",
    "",
    question.prompt,
    "",
    `Why it matters: ${question.why_it_matters}`,
    "",
    `Useful answer styles: ${question.options.join(" | ")}`
  ].join("\n");
}

function interviewTurnsFromSession(session: Session, opening: string) {
  const turns: Array<{ role: "user" | "assistant"; text: string }> = [{ role: "user", text: session.initial_use_case }];
  const assumptions = session.current_summary?.assumptions ?? [];
  const capturedAnswers = assumptions
    .map((item) => {
      const match = item.text.match(/^Interview answer for '(.+)': ([\s\S]+)$/);
      return match ? { question: match[1], answer: match[2] } : null;
    })
    .filter((item): item is { question: string; answer: string } => Boolean(item));
  capturedAnswers.forEach((item, index) => {
    turns.push({ role: "assistant", text: index === 0 ? item.question : `Next question: ${item.question}` });
    turns.push({ role: "user", text: item.answer });
  });
  turns.push({ role: "assistant", text: opening });
  return turns;
}

function PricingCheckpointCard({
  checkpoint,
  loading,
  onUseProfile,
  onProceedWithoutHeadline,
  busy
}: {
  checkpoint?: PricingCheckpoint;
  loading: boolean;
  onUseProfile: (profileId: string) => void;
  onProceedWithoutHeadline: () => void;
  busy: boolean;
}) {
  if (loading) {
    return <div className="border border-awsBorder bg-surface p-4 text-sm text-awsTextMuted">Loading pricing checkpoint...</div>;
  }
  if (!checkpoint) {
    return null;
  }
  const closure = checkpoint.closure_report;
  const profileUsed = closure.scenario_profile_used;
  return (
    <div className="border border-awsBorder bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">Pricing Checkpoint</div>
          <p className="mt-1 text-sm leading-6 text-awsTextSecondary">{checkpoint.message}</p>
        </div>
        <span className="border border-awsBorder bg-white px-2 py-1 text-xs text-awsTextMuted">{titleize(closure.pricing_maturity)}</span>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <Metric label="Confirmed" value={String(closure.confirmed_drivers.length)} />
        <Metric label="Assumed" value={String(closure.assumed_drivers.length)} />
        <Metric label="Missing" value={String(closure.missing_drivers.length)} />
        <Metric label="Procurement" value={closure.procurement_ready ? "Ready" : "Not ready"} />
      </div>
      {profileUsed ? <Banner tone="info" text="A scenario profile is active. Pricing is directional and must be replaced with traffic forecasts, CDN logs, or event schedule data before budgeting." /> : null}
      {closure.missing_drivers.length ? (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {closure.missing_drivers.slice(0, 6).map((driver) => (
            <div key={driver.driver_name} className="border border-awsBorder bg-white p-3 text-sm">
              <div className="font-semibold">{driver.display_name}</div>
              <p className="mt-1 text-awsTextSecondary">{driver.why_needed}</p>
            </div>
          ))}
        </div>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2">
        {checkpoint.scenario_profiles.map((profile) => (
          <Button key={profile.id} icon={Sparkles} variant="secondary" disabled={busy} onClick={() => onUseProfile(profile.id)}>{profile.label}</Button>
        ))}
        <Button icon={Lock} variant="secondary" disabled={busy} onClick={onProceedWithoutHeadline}>Proceed without headline pricing</Button>
      </div>
    </div>
  );
}

function ClaimCard({ title, claims }: { title: string; claims: Array<{ id: string; text: string; evidence_ids: string[]; confidence: string; citation_status: string }> }) {
  return (
    <div className="border border-awsBorder bg-surface p-4">
      <div className="mb-3 text-sm font-semibold">{title}</div>
      <div className="space-y-3">
        {claims.slice(0, 5).map((claim) => (
          <div key={claim.id} className="border border-awsBorder bg-white p-3">
            <p className="text-sm leading-6 text-awsTextSecondary">{claim.text}</p>
            <div className="mt-2 flex flex-wrap gap-2 text-xs text-awsTextMuted">
              <span>{claim.confidence}</span>
              <span>{claim.citation_status}</span>
              {claim.evidence_ids.length ? <span>{claim.evidence_ids.join(", ")}</span> : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ArchitectureEditorCard({ architecture, draft, onChange }: { architecture: ArchitectureSpec; draft: ArchitectureDraft; onChange: (draft: ArchitectureDraft) => void }) {
  const update = (field: keyof ArchitectureDraft, value: string) => onChange({ ...draft, [field]: value });
  return (
    <div className="border border-awsBorder bg-surface p-4">
      <div className="mb-3 flex items-start justify-between">
        <div>
          <h3 className="text-lg font-semibold">{architecture.title}</h3>
          <p className="mt-1 text-sm leading-6 text-awsTextSecondary">{architecture.selected_services.map((item) => item.service).join(", ")}</p>
        </div>
        <span className="border border-awsOrange/50 px-2 py-1 text-xs uppercase text-awsOrange">{architecture.mode}</span>
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        <TextArea label="Summary" value={draft.summary} onChange={(value) => update("summary", value)} />
        <TextArea label="Security controls" value={draft.security_controls_text} onChange={(value) => update("security_controls_text", value)} hint="One control per line: name: rationale" />
        <TextArea label="Observability controls" value={draft.observability_controls_text} onChange={(value) => update("observability_controls_text", value)} hint="One control per line: name: rationale" />
        <TextArea label="Scaling strategy" value={draft.scaling_strategy} onChange={(value) => update("scaling_strategy", value)} />
        <TextArea label="Resilience strategy" value={draft.resilience_strategy} onChange={(value) => update("resilience_strategy", value)} />
        <TextArea label="Cost optimization" value={draft.cost_optimization_strategy} onChange={(value) => update("cost_optimization_strategy", value)} />
      </div>
    </div>
  );
}

function ValidationPanel({ issues }: { issues: ArchitectureValidationIssue[] }) {
  if (issues.length === 0) {
    return <div className="border border-awsSuccess/40 bg-[#f1f8f5] p-4 text-sm text-awsTextSecondary">Architecture validation passed for security, observability, and tool governance guardrails.</div>;
  }
  return (
    <div className="border border-awsWarning/50 bg-[#fff8e5] p-4">
      <div className="mb-3 flex items-center gap-2 font-semibold"><ShieldCheck className="h-5 w-5 text-awsWarning" /> Architecture validation</div>
      <div className="space-y-2">
        {issues.map((issue) => (
          <div key={`${issue.mode}-${issue.code}-${issue.message}`} className="flex flex-wrap items-center gap-2 text-sm text-awsTextSecondary">
            <span className={`border px-2 py-1 text-xs uppercase ${issue.severity === "critical" ? "border-awsDanger/50 text-awsDanger" : issue.severity === "important" ? "border-awsWarning/60 text-awsWarning" : "border-awsBorder text-awsTextMuted"}`}>{issue.severity}</span>
            <span>{issue.mode ? `${issue.mode}: ` : ""}{issue.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function RevisionHistory({ revisions }: { revisions: ArchitectureRevision[] }) {
  return (
    <div className="border border-awsBorder bg-surface p-4">
      <div className="mb-3 flex items-center gap-2 font-semibold"><History className="h-4 w-4 text-awsOrange" /> Revision history</div>
      <div className="space-y-2 text-sm text-awsTextSecondary">
        {revisions.slice(-5).reverse().map((revision) => (
          <div key={revision.id} className="flex flex-wrap items-center justify-between gap-3 border border-awsBorder bg-white p-3">
            <span>Revision {revision.version}: {revision.reason}</span>
            <span className="text-awsTextMuted">{new Date(revision.created_at).toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TextArea({ label, value, onChange, hint }: { label: string; value: string; onChange: (value: string) => void; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm font-semibold">{label}</span>
      <textarea className="min-h-32 w-full resize-y border border-awsBorder bg-white p-3 text-sm leading-6 text-awsTextSecondary outline-none focus:border-awsOrange" value={value} onChange={(event) => onChange(event.target.value)} />
      {hint ? <span className="mt-1 block text-xs text-awsTextMuted">{hint}</span> : null}
    </label>
  );
}

function architectureToDraft(architecture: ArchitectureSpec): ArchitectureDraft {
  return {
    summary: architecture.summary,
    scaling_strategy: architecture.scaling_strategy,
    resilience_strategy: architecture.resilience_strategy,
    cost_optimization_strategy: architecture.cost_optimization_strategy,
    security_controls_text: formatControls(architecture.security_controls),
    observability_controls_text: formatControls(architecture.observability_controls)
  };
}

function draftToPatch(draft: ArchitectureDraft) {
  return {
    summary: draft.summary,
    scaling_strategy: draft.scaling_strategy,
    resilience_strategy: draft.resilience_strategy,
    cost_optimization_strategy: draft.cost_optimization_strategy,
    security_controls: parseControls(draft.security_controls_text),
    observability_controls: parseControls(draft.observability_controls_text)
  };
}

function formatControls(controls: Array<{ name: string; rationale: string }>) {
  return controls.map((control) => `${control.name}: ${control.rationale}`).join("\n");
}

function parseControls(value: string) {
  return value.split("\n").map((line) => {
    const [name, ...rest] = line.split(":");
    return { name: name.trim(), rationale: rest.join(":").trim() };
  }).filter((item) => item.name);
}

function Checkpoint({ readiness, onAssume }: { readiness: Readiness; onAssume: () => void }) {
  return (
    <div className="border border-awsBorder bg-white p-4">
      <div className="mb-2 flex items-center gap-2 font-semibold"><AlertTriangle className="h-5 w-5 text-awsWarning" /> Optional checks before research</div>
      <p className="text-sm text-awsTextSecondary">Archway can proceed with visible assumptions, or you can answer any remaining items first.</p>
      <ul className="mt-3 space-y-2 text-sm text-awsTextSecondary">
        {readiness.recommended_minimum_questions.slice(0, 3).map((question) => <li key={question.id}>{question.prompt}</li>)}
      </ul>
      <Button icon={ChevronRight} onClick={onAssume} className="mt-4">Let Archway assume and proceed</Button>
    </div>
  );
}

function ConversationBubble({ role, text }: { role: "user" | "assistant"; text: string }) {
  const Icon = role === "assistant" ? Bot : MessageSquareText;
  return (
    <div className={`mx-auto flex max-w-5xl gap-3 ${role === "user" ? "justify-end" : "justify-start"}`}>
      <div className={`w-fit max-w-[82%] border p-4 ${role === "user" ? "border-awsBorder bg-awsPanelSoft" : "border-awsOrange/40 bg-surface"}`}>
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Icon className="h-4 w-4 text-awsOrange" /> {role === "assistant" ? "Archway" : "You"}</div>
        <div className="whitespace-pre-wrap text-sm leading-6 text-awsTextSecondary">{text}</div>
      </div>
    </div>
  );
}

function ProgressTimeline({ active }: { active: boolean }) {
  const steps = ["Plan questions", "Fetch evidence", "Price services", "Build claims", "Check consistency", "Assemble dossier"];
  return (
    <div className="grid gap-2 md:grid-cols-3 xl:grid-cols-6">
      {steps.map((step, index) => (
        <div key={step} className="border border-awsBorder bg-surface p-3">
          <div className="mb-2 flex items-center gap-2">{active && index === 1 ? <Loader2 className="h-4 w-4 animate-spin text-awsOrange" /> : <CheckCircle2 className="h-4 w-4 text-awsSuccess" />}</div>
          <div className="text-sm">{step}</div>
        </div>
      ))}
    </div>
  );
}

function EmptyWorkspace() {
  return (
    <div className="grid min-h-full place-items-center p-8">
      <div className="max-w-xl text-center">
        <ShieldCheck className="mx-auto mb-4 h-12 w-12 text-awsOrange" />
        <h1 className="text-2xl font-semibold">Start with a rough AI use case</h1>
        <p className="mt-3 text-awsTextSecondary">Archway will shape the brief, preserve assumptions, research evidence, estimate cost responsibly, and generate diagrams through the existing compiler.</p>
      </div>
    </div>
  );
}

function Panel({ title, icon: Icon, children }: { title: string; icon: typeof Activity; children: React.ReactNode }) {
  return (
    <section className="archway-scroll flex-1 overflow-y-auto p-5">
      <div className="mb-5 flex items-center gap-2">
        <Icon className="h-5 w-5 text-awsOrange" />
        <h2 className="text-xl font-semibold">{title}</h2>
      </div>
      {children}
    </section>
  );
}

function Button({ children, icon: Icon, variant = "primary", disabled, onClick, className = "", ariaLabel, title }: { children?: React.ReactNode; icon?: typeof Activity; variant?: "primary" | "secondary" | "ghost"; disabled?: boolean; onClick?: () => void; className?: string; ariaLabel?: string; title?: string }) {
  const styles = variant === "primary" ? "border-awsOrange bg-awsOrange text-[#111827] hover:bg-[#ffad33]" : variant === "secondary" ? "border-awsBorder bg-awsPanelSoft text-awsTextPrimary hover:border-awsOrange" : "border-transparent bg-transparent text-awsTextSecondary hover:border-awsBorder";
  return (
    <button aria-label={ariaLabel} title={title} disabled={disabled} onClick={onClick} className={`inline-flex min-h-10 items-center justify-center gap-2 border px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}>
      {Icon ? <Icon className={`h-4 w-4 ${Icon === Loader2 ? "animate-spin" : ""}`} /> : null}
      {children}
    </button>
  );
}

function StatusPill({ status }: { status: HealthSummary["status"] }) {
  return <span className={`inline-flex items-center border px-2 py-1 text-xs font-semibold uppercase ${status === "ready" ? "border-awsSuccess/50 text-awsSuccess" : status === "failed" ? "border-awsDanger/50 text-awsDanger" : "border-awsWarning/50 text-awsWarning"}`}>{status}</span>;
}

function statusClass(status: HealthSummary["status"]) {
  return `h-5 w-5 ${status === "ready" ? "text-awsSuccess" : status === "failed" ? "text-awsDanger" : "text-awsWarning"}`;
}

function Banner({ tone, text }: { tone: "info" | "warning" | "danger"; text: string }) {
  const toneClass =
    tone === "danger"
      ? "border-awsDanger/50 bg-[#fff1f2] text-awsDanger"
      : tone === "warning"
        ? "border-awsOrange/50 bg-[#fff8eb] text-awsTextSecondary"
        : "border-awsInfo/50 bg-[#eef6ff] text-awsTextSecondary";
  return <div className={`border p-4 text-sm ${toneClass}`}>{text}</div>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="border border-awsBorder bg-surface p-4"><div className="text-xs uppercase tracking-[0.12em] text-awsTextMuted">{label}</div><div className="mt-2 text-2xl font-semibold">{value}</div></div>;
}

function BriefSection({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="border border-awsBorder bg-surface p-3">
      <div className="mb-2 text-xs uppercase tracking-[0.12em] text-awsTextMuted">{title}</div>
      <ul className="space-y-2 text-awsTextSecondary">
        {items.slice(0, 5).map((item) => <li key={item} title={item} className="line-clamp-4">{item}</li>)}
      </ul>
    </div>
  );
}

function ListCard({ title, items }: { title: string; items: string[] }) {
  return <div className="border border-awsBorder bg-white p-3"><div className="mb-2 text-sm font-semibold">{title}</div><ul className="space-y-2 text-sm leading-6 text-awsTextSecondary">{items.map((item) => <li key={item}>{item}</li>)}</ul></div>;
}

function MarkdownBlock({ markdown, unframed = false }: { markdown: string; unframed?: boolean }) {
  const html = useMemo(() => sanitizeMarkdown(markdown), [markdown]);
  const className = unframed
    ? "markdown text-sm leading-6 text-awsTextSecondary"
    : "markdown border border-awsBorder bg-surface p-4 text-sm leading-6 text-awsTextSecondary";
  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}

function Table({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto border border-awsBorder">
      <table className="min-w-full border-collapse bg-surface text-sm">
        <thead><tr>{headers.map((header) => <th key={header} className="border-b border-awsBorder p-3 text-left text-awsTextMuted">{header}</th>)}</tr></thead>
        <tbody>{rows.map((row) => <tr key={row.join("|")}>{row.map((cell, index) => <td key={`${cell}-${index}`} className="border-b border-awsBorder/70 p-3 align-top text-awsTextSecondary">{cell}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

const skeletonChecks: HealthCheckResult[] = [
  { id: "backend", label: "Backend API", status: "degraded", required: true, reason: "Checking backend availability.", details: {} },
  { id: "database", label: "Local session database", status: "degraded", required: true, reason: "Checking SQLite.", details: {} },
  { id: "diagram", label: "Existing diagram compiler", status: "degraded", required: true, reason: "Checking local compiler import.", details: {} }
];
