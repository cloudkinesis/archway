import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  Loader2,
  RotateCcw,
  Save,
  ChevronRight,
  ShieldCheck,
  History,
  Activity,
  RefreshCw
} from "lucide-react";
import { api } from "../../lib/api";
import type {
  Session,
  ArchitectureSpec,
  ArchitectureValidationIssue,
  ArchitectureRevision,
  DiagramGalleryResult,
  JobRun
} from "../../lib/types";

type LatestJobs = Partial<Record<JobRun["operation"], JobRun | null>>;
type View = "synthesis" | "research" | "architecture" | "diagrams" | "diagnostics";

type ArchitectureDraft = Pick<ArchitectureSpec, "summary" | "scaling_strategy" | "resilience_strategy" | "cost_optimization_strategy"> & {
  security_controls_text: string;
  observability_controls_text: string;
};

interface ArchitectureViewerProps {
  session: Session;
  setSession: (session: Session) => void;
  architectures: ArchitectureSpec[];
  setArchitectures: (items: ArchitectureSpec[]) => void;
  architectureValidationIssues: ArchitectureValidationIssue[];
  setArchitectureValidationIssues: (items: ArchitectureValidationIssue[]) => void;
  architectureRevisions: ArchitectureRevision[];
  setArchitectureRevisions: (items: ArchitectureRevision[]) => void;
  setGalleries: (items: DiagramGalleryResult[]) => void;
  setView: (view: View) => void;
  latestJobs: LatestJobs;
  setLatestJobs: (jobs: LatestJobs) => void;
}

export function ArchitectureViewer({
  session,
  setSession,
  architectures,
  setArchitectures,
  architectureValidationIssues,
  setArchitectureValidationIssues,
  architectureRevisions,
  setArchitectureRevisions,
  setGalleries,
  setView,
  latestJobs,
  setLatestJobs
}: ArchitectureViewerProps) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, ArchitectureDraft>>({});
  const [hydratedLatestJobId, setHydratedLatestJobId] = useState<string | null>(null);

  useEffect(() => {
    const latest = latestJobs.architecture;
    if (architectures.length === 0 && latest?.id && latest.id !== jobId && ["queued", "running", "succeeded"].includes(latest.status)) {
      setJobId(latest.id);
    }
  }, [architectures.length, jobId, latestJobs.architecture]);

  const job = useJobPolling(session.id, jobId, async () => {
    const result = await api.hydrateSession(session.id);
    setSession(result.session);
    setArchitectures(result.architecture?.architectures ?? []);
    setArchitectureValidationIssues(result.architecture?.validation_issues ?? []);
    setArchitectureRevisions(result.architecture?.revisions ?? []);
    setLatestJobs(result.jobs ?? {});
  });

  const generate = useMutation({
    mutationFn: () => api.generateArchitecture(session.id),
    onSuccess: (result) => setJobId(result.job.id)
  });

  useEffect(() => {
    const latest = latestJobs.architecture;
    if (architectures.length > 0 || latest?.status !== "succeeded" || latest.id === hydratedLatestJobId) {
      return;
    }
    setHydratedLatestJobId(latest.id);
    api.hydrateSession(session.id)
      .then((result) => {
        setSession(result.session);
        setArchitectures(result.architecture?.architectures ?? []);
        setArchitectureValidationIssues(result.architecture?.validation_issues ?? []);
        setArchitectureRevisions(result.architecture?.revisions ?? []);
        setLatestJobs(result.jobs ?? {});
      })
      .catch(() => setHydratedLatestJobId(null));
  }, [
    architectures.length,
    hydratedLatestJobId,
    latestJobs.architecture,
    session.id,
    setArchitectureRevisions,
    setArchitectureValidationIssues,
    setArchitectures,
    setLatestJobs,
    setSession
  ]);

  const save = useMutation({
    mutationFn: () => api.updateArchitecture(session.id, {
      reason: "User-edited architecture revision",
      specs: Object.fromEntries(architectures.map((architecture) => [
        architecture.mode,
        draftToPatch(drafts[architecture.mode] ?? architectureToDraft(architecture))
      ]))
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
    setDrafts(
      Object.fromEntries(
        architectures.map((architecture) => [architecture.mode, architectureToDraft(architecture)])
      )
    );
  }, [architectures]);

  const hasCriticalIssues = architectureValidationIssues.some((issue) => issue.severity === "critical");

  return (
    <Panel title="Architecture" icon={LayoutDashboard}>
      {architectures.length === 0 ? (
        <div className="space-y-4">
          {job.job ? <JobProgress job={job.job} onCancel={() => job.cancel.mutate()} /> : null}
          <Button
            icon={generate.isPending || job.isActive ? Loader2 : LayoutDashboard}
            disabled={generate.isPending || job.isActive}
            onClick={() => generate.mutate()}
          >
            {generate.isPending || job.isActive ? "Planning" : "Generate POC and production specs"}
          </Button>
          {job.refreshError ? (
            <Banner
              tone="warning"
              text={`Architecture finished, but the browser could not refresh the specs yet: ${job.refreshError}`}
            />
          ) : null}
          {job.job?.status === "failed" ? (
            <Banner
              tone="warning"
              text={job.job.error ?? "Architecture planning needs a retry. Diagnostics were recorded and the session remains usable."}
            />
          ) : null}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 border border-awsBorder bg-surface p-4">
            <div>
              <div className="font-semibold">Revision {architectureRevisions[architectureRevisions.length - 1]?.version ?? 1}</div>
              <p className="text-sm text-awsTextSecondary">Edits are saved as new revisions and diagrams regenerate only from the active revision.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                icon={regenerate.isPending ? Loader2 : RotateCcw}
                variant="secondary"
                disabled={regenerate.isPending || save.isPending}
                onClick={() => regenerate.mutate()}
              >
                Regenerate from active
              </Button>
              <Button
                icon={save.isPending ? Loader2 : Save}
                disabled={save.isPending || regenerate.isPending}
                onClick={() => save.mutate()}
              >
                Save revision
              </Button>
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

function ArchitectureEditorCard({
  architecture,
  draft,
  onChange
}: {
  architecture: ArchitectureSpec;
  draft: ArchitectureDraft;
  onChange: (draft: ArchitectureDraft) => void;
}) {
  const update = (field: keyof ArchitectureDraft, value: string) => onChange({ ...draft, [field]: value });
  const securityControls = parseControls(draft.security_controls_text);
  const observabilityControls = parseControls(draft.observability_controls_text);
  return (
    <div className="border border-awsBorder bg-surface p-4">
      <div className="mb-3 flex items-start justify-between">
        <div>
          <h3 className="text-lg font-semibold">{architecture.title}</h3>
          <p className="mt-1 text-sm leading-6 text-awsTextSecondary">
            {architecture.selected_services.map((item) => item.service).join(", ")}
          </p>
        </div>
        <span className="border border-awsOrange/50 px-2 py-1 text-xs uppercase text-awsOrange">
          {architecture.mode}
        </span>
      </div>
      <div className="mb-4 grid gap-3 xl:grid-cols-3">
        <ArchitectureReadCard title="Summary" lines={[draft.summary]} />
        <ArchitectureReadCard
          title="Security controls"
          lines={securityControls.map((item) => `${item.name}: ${item.rationale}`)}
        />
        <ArchitectureReadCard
          title="Observability controls"
          lines={observabilityControls.map((item) => `${item.name}: ${item.rationale}`)}
        />
        <ArchitectureReadCard title="Scaling" lines={[draft.scaling_strategy]} />
        <ArchitectureReadCard title="Resilience" lines={[draft.resilience_strategy]} />
        <ArchitectureReadCard title="Cost posture" lines={[draft.cost_optimization_strategy]} />
      </div>
      <details className="border border-awsBorder bg-white p-3">
        <summary className="cursor-pointer text-sm font-semibold">Edit architecture fields</summary>
        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          <TextArea label="Summary" value={draft.summary} onChange={(value) => update("summary", value)} />
          <TextArea
            label="Security controls"
            value={draft.security_controls_text}
            onChange={(value) => update("security_controls_text", value)}
            hint="One control per line: name: rationale"
          />
          <TextArea
            label="Observability controls"
            value={draft.observability_controls_text}
            onChange={(value) => update("observability_controls_text", value)}
            hint="One control per line: name: rationale"
          />
          <TextArea label="Scaling strategy" value={draft.scaling_strategy} onChange={(value) => update("scaling_strategy", value)} />
          <TextArea label="Resilience strategy" value={draft.resilience_strategy} onChange={(value) => update("resilience_strategy", value)} />
          <TextArea label="Cost optimization" value={draft.cost_optimization_strategy} onChange={(value) => update("cost_optimization_strategy", value)} />
        </div>
      </details>
    </div>
  );
}

function ArchitectureReadCard({ title, lines }: { title: string; lines: string[] }) {
  const clean = lines.map((line) => presentationText(line)).filter(Boolean).slice(0, 4);
  return (
    <section className="border border-awsBorder bg-white p-3">
      <h4 className="text-sm font-semibold">{title}</h4>
      {clean.length ? (
        <ul className="mt-2 space-y-2 text-sm leading-6 text-awsTextSecondary">
          {clean.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-awsTextMuted">No generated narrative is available for this section yet.</p>
      )}
    </section>
  );
}

function ValidationPanel({ issues }: { issues: ArchitectureValidationIssue[] }) {
  if (issues.length === 0) {
    return (
      <div className="border border-awsSuccess/40 bg-[#f1f8f5] p-4 text-sm text-awsTextSecondary">
        Architecture validation passed for security, observability, and tool governance guardrails.
      </div>
    );
  }
  return (
    <div className="border border-awsWarning/50 bg-[#fff8e5] p-4">
      <div className="mb-3 flex items-center gap-2 font-semibold">
        <ShieldCheck className="h-5 w-5 text-awsWarning" /> Architecture validation
      </div>
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
      <div className="mb-3 flex items-center gap-2 font-semibold">
        <History className="h-4 w-4 text-awsOrange" /> Revision history
      </div>
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

function TextArea({
  label,
  value,
  onChange,
  hint
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm font-semibold">{label}</span>
      <textarea
        className="min-h-32 w-full resize-y border border-awsBorder bg-white p-3 text-sm leading-6 text-awsTextSecondary outline-none focus:border-awsOrange"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
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

function presentationText(value: string | null | undefined) {
  if (!value) return "";
  return value.trim();
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

function Button({
  children,
  icon: Icon,
  variant = "primary",
  disabled,
  onClick,
  className = "",
  ariaLabel,
  title
}: {
  children?: React.ReactNode;
  icon?: typeof Activity;
  variant?: "primary" | "secondary" | "ghost";
  disabled?: boolean;
  onClick?: () => void;
  className?: string;
  ariaLabel?: string;
  title?: string;
}) {
  const styles =
    variant === "primary"
      ? "border-awsOrange bg-awsOrange text-[#111827] hover:bg-[#ffad33]"
      : variant === "secondary"
        ? "border-awsBorder bg-awsPanelSoft text-awsTextPrimary hover:border-awsOrange"
        : "border-transparent bg-transparent text-awsTextSecondary hover:border-awsBorder";
  return (
    <button
      aria-label={ariaLabel}
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex min-h-10 items-center justify-center gap-2 border px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
    >
      {Icon ? <Icon className={`h-4 w-4 ${Icon === Loader2 ? "animate-spin" : ""}`} /> : null}
      {children}
    </button>
  );
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

function useJobPolling(sessionId: string, jobId: string | null, onSucceeded: () => Promise<void>) {
  const [completedJobId, setCompletedJobId] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
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
    setRefreshError(null);
  }, [jobId]);
  useEffect(() => {
    if (job?.status === "succeeded" && completedJobId !== job.id) {
      setCompletedJobId(job.id);
      onSucceeded().catch((error) => setRefreshError((error as Error).message));
    }
  }, [completedJobId, job?.id, job?.status, onSucceeded]);
  return {
    job,
    cancel,
    refreshError,
    isActive: job?.status === "queued" || job?.status === "running"
  };
}
