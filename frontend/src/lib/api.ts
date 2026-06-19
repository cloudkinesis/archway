import type { ArchitectureResponse, BuildStatusSummary, DiagramGalleryResult, ExportBundle, HealthSummary, HydratedSession, JobRun, LiveAgentStatus, PricingCheckpoint, Readiness, ResearchReport, Session } from "./types";

const API_BASE = import.meta.env.VITE_ARCHWAY_API_BASE ?? "http://127.0.0.1:8000/api";

interface RequestOptions extends RequestInit {
  timeout?: number;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const timeoutMs = options.timeout !== undefined ? options.timeout : 30000;
  const controller = new AbortController();
  let timeoutId: number | undefined;
  
  if (timeoutMs > 0) {
    timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  }
  
  if (options.signal) {
    if (options.signal.aborted) {
      controller.abort();
    } else {
      options.signal.addEventListener("abort", () => controller.abort());
    }
  }

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      signal: controller.signal,
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
  } finally {
    if (timeoutId !== undefined) {
      clearTimeout(timeoutId);
    }
  }
}

export const artifactUrl = (sessionId: string, artifactId: string) => `${API_BASE}/sessions/${sessionId}/artifacts/${artifactId}`;

export const api = {
  health: () => request<HealthSummary>("/health", { timeout: 10000 }),
  buildStatus: () => request<BuildStatusSummary>("/build/status", { timeout: 10000 }),
  createSession: (initial_use_case: string) =>
    request<{ session: Session; readiness: Readiness; message?: string }>("/sessions", {
      method: "POST",
      body: JSON.stringify({ initial_use_case }),
      timeout: 60000
    }),
  listSessions: () => request<{ sessions: Session[] }>("/sessions", { timeout: 15000 }),
  hydrateSession: (sessionId: string) =>
    request<HydratedSession>(`/sessions/${sessionId}/hydrate`, { timeout: 120000 }),
  sendSynthesis: (sessionId: string, message: string) =>
    request<{ message: string; brief: Session["current_summary"]; readiness: Readiness }>(`/sessions/${sessionId}/synthesis/message`, {
      method: "POST",
      body: JSON.stringify({ message }),
      timeout: 60000
    }),
  proceed: (sessionId: string, assume_and_proceed: boolean) =>
    request<{ proceeded: boolean; message: string; questions?: unknown[]; readiness: Readiness }>(`/sessions/${sessionId}/synthesis/proceed`, {
      method: "POST",
      body: JSON.stringify({ assume_and_proceed }),
      timeout: 60000
    }),
  runResearch: (sessionId: string) =>
    request<{ job: JobRun }>(`/sessions/${sessionId}/research/run`, { method: "POST", timeout: 30000 }),
  getResearchReport: (sessionId: string) =>
    request<{ report: ResearchReport }>(`/sessions/${sessionId}/research/report`, { timeout: 120000 }),
  getPricingCheckpoint: (sessionId: string) =>
    request<{ checkpoint: PricingCheckpoint }>(`/sessions/${sessionId}/pricing/checkpoint`, { timeout: 120000 }),
  usePricingProfile: (sessionId: string, profile_id: string) =>
    request<{ checkpoint: PricingCheckpoint; report: ResearchReport }>(`/sessions/${sessionId}/pricing/checkpoint/use-profile`, {
      method: "POST",
      body: JSON.stringify({ profile_id }),
      timeout: 60000
    }),
  proceedWithoutPricingHeadline: (sessionId: string) =>
    request<{ checkpoint: PricingCheckpoint; report?: ResearchReport }>(`/sessions/${sessionId}/pricing/checkpoint/proceed-without-headline`, { method: "POST", timeout: 60000 }),
  generateArchitecture: (sessionId: string) =>
    request<{ job: JobRun }>(`/sessions/${sessionId}/architecture/generate`, { method: "POST", timeout: 30000 }),
  getArchitecture: (sessionId: string) =>
    request<ArchitectureResponse>(`/sessions/${sessionId}/architecture`, { timeout: 120000 }),
  updateArchitecture: (sessionId: string, payload: { reason: string; specs: Record<string, unknown> }) =>
    request<ArchitectureResponse>(`/sessions/${sessionId}/architecture`, {
      method: "PATCH",
      body: JSON.stringify(payload),
      timeout: 60000
    }),
  regenerateArchitecture: (sessionId: string) =>
    request<ArchitectureResponse>(`/sessions/${sessionId}/architecture/regenerate`, { method: "POST", timeout: 60000 }),
  generateDiagrams: (sessionId: string) =>
    request<{ job: JobRun }>(`/sessions/${sessionId}/diagrams/generate`, { method: "POST", timeout: 30000 }),
  getDiagrams: (sessionId: string) =>
    request<{ galleries: DiagramGalleryResult[] }>(`/sessions/${sessionId}/diagrams`, { timeout: 120000 }),
  getJob: (sessionId: string, jobId: string) =>
    request<{ job: JobRun }>(`/sessions/${sessionId}/jobs/${jobId}`, { timeout: 15000 }),
  cancelJob: (sessionId: string, jobId: string) =>
    request<{ job: JobRun }>(`/sessions/${sessionId}/jobs/${jobId}/cancel`, { method: "POST", timeout: 15000 }),
  generateExport: (sessionId: string) =>
    request<{ job: JobRun }>(`/sessions/${sessionId}/export/generate`, { method: "POST", timeout: 30000 }),
  getExport: (sessionId: string) =>
    request<{ export: ExportBundle }>(`/sessions/${sessionId}/export/package`, { timeout: 120000 }),
  getLiveAgentStatus: (sessionId: string) =>
    request<LiveAgentStatus>(`/sessions/${sessionId}/agentic/live-status`, { timeout: 15000 }),
  diagnostics: (sessionId: string) => request<{ logs: unknown[]; health: HealthSummary }>(`/sessions/${sessionId}/diagnostics`, { timeout: 30000 })
};
