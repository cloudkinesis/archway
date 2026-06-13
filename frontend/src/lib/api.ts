import type { ArchitectureResponse, BuildStatusSummary, DiagramGalleryResult, ExportBundle, HealthSummary, HydratedSession, JobRun, LiveAgentStatus, PricingCheckpoint, Readiness, ResearchReport, Session } from "./types";

const API_BASE = import.meta.env.VITE_ARCHWAY_API_BASE ?? "http://127.0.0.1:8000/api";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {})
    }
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Archway API error ${response.status}`);
  }
  return response.json();
}

export const artifactUrl = (sessionId: string, artifactId: string) => `${API_BASE}/sessions/${sessionId}/artifacts/${artifactId}`;

export const api = {
  health: () => request<HealthSummary>("/health"),
  buildStatus: () => request<BuildStatusSummary>("/build/status"),
  createSession: (initial_use_case: string) =>
    request<{ session: Session; readiness: Readiness; message?: string }>("/sessions", {
      method: "POST",
      body: JSON.stringify({ initial_use_case })
    }),
  listSessions: () => request<{ sessions: Session[] }>("/sessions"),
  hydrateSession: (sessionId: string) =>
    request<HydratedSession>(`/sessions/${sessionId}/hydrate`),
  sendSynthesis: (sessionId: string, message: string) =>
    request<{ message: string; brief: Session["current_summary"]; readiness: Readiness }>(`/sessions/${sessionId}/synthesis/message`, {
      method: "POST",
      body: JSON.stringify({ message })
    }),
  proceed: (sessionId: string, assume_and_proceed: boolean) =>
    request<{ proceeded: boolean; message: string; questions?: unknown[]; readiness: Readiness }>(`/sessions/${sessionId}/synthesis/proceed`, {
      method: "POST",
      body: JSON.stringify({ assume_and_proceed })
    }),
  runResearch: (sessionId: string) =>
    request<{ job: JobRun }>(`/sessions/${sessionId}/research/run`, { method: "POST" }),
  getResearchReport: (sessionId: string) =>
    request<{ report: ResearchReport }>(`/sessions/${sessionId}/research/report`),
  getPricingCheckpoint: (sessionId: string) =>
    request<{ checkpoint: PricingCheckpoint }>(`/sessions/${sessionId}/pricing/checkpoint`),
  usePricingProfile: (sessionId: string, profile_id: string) =>
    request<{ checkpoint: PricingCheckpoint; report: ResearchReport }>(`/sessions/${sessionId}/pricing/checkpoint/use-profile`, {
      method: "POST",
      body: JSON.stringify({ profile_id })
    }),
  proceedWithoutPricingHeadline: (sessionId: string) =>
    request<{ checkpoint: PricingCheckpoint; report?: ResearchReport }>(`/sessions/${sessionId}/pricing/checkpoint/proceed-without-headline`, { method: "POST" }),
  generateArchitecture: (sessionId: string) =>
    request<{ job: JobRun }>(`/sessions/${sessionId}/architecture/generate`, { method: "POST" }),
  getArchitecture: (sessionId: string) =>
    request<ArchitectureResponse>(`/sessions/${sessionId}/architecture`),
  updateArchitecture: (sessionId: string, payload: { reason: string; specs: Record<string, unknown> }) =>
    request<ArchitectureResponse>(`/sessions/${sessionId}/architecture`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  regenerateArchitecture: (sessionId: string) =>
    request<ArchitectureResponse>(`/sessions/${sessionId}/architecture/regenerate`, { method: "POST" }),
  generateDiagrams: (sessionId: string) =>
    request<{ job: JobRun }>(`/sessions/${sessionId}/diagrams/generate`, { method: "POST" }),
  getDiagrams: (sessionId: string) =>
    request<{ galleries: DiagramGalleryResult[] }>(`/sessions/${sessionId}/diagrams`),
  getJob: (sessionId: string, jobId: string) =>
    request<{ job: JobRun }>(`/sessions/${sessionId}/jobs/${jobId}`),
  cancelJob: (sessionId: string, jobId: string) =>
    request<{ job: JobRun }>(`/sessions/${sessionId}/jobs/${jobId}/cancel`, { method: "POST" }),
  generateExport: (sessionId: string) =>
    request<{ job: JobRun }>(`/sessions/${sessionId}/export/generate`, { method: "POST" }),
  getExport: (sessionId: string) =>
    request<{ export: ExportBundle }>(`/sessions/${sessionId}/export/package`),
  getLiveAgentStatus: (sessionId: string) =>
    request<LiveAgentStatus>(`/sessions/${sessionId}/agentic/live-status`),
  diagnostics: (sessionId: string) => request<{ logs: unknown[]; health: HealthSummary }>(`/sessions/${sessionId}/diagnostics`)
};
