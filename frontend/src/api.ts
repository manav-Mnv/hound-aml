import type { Alert, CaseDetail, Status, Subgraph, TraceEvent } from "./types";

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  status: () => j<Status>("/api/status"),
  overview: (t: string) => j<any>(`/api/${t}/overview`),
  alerts: (t: string) => j<Alert[]>(`/api/${t}/alerts`),
  triage: (t: string) => j<{ scored: number; ms: number }>(`/api/${t}/triage`, { method: "POST" }),
  cases: (t: string) => j<any[]>(`/api/${t}/cases`),
  case: (t: string, id: string) => j<CaseDetail>(`/api/${t}/cases/${id}`),
  decide: (t: string, id: string, decision: string, note: string, analyst = "you") =>
    j<any>(`/api/${t}/cases/${id}/decision`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, note, analyst }),
    }),
  neighborhood: (t: string, id: string) => j<Subgraph>(`/api/${t}/entity/${encodeURIComponent(id)}/neighborhood`),
  memory: (t: string) => j<any>(`/api/${t}/memory`),
  consortium: () => j<any>("/api/consortium"),
  evals: () => j<Record<string, any>>("/api/eval"),
  schema: () => j<any>("/api/schema"),
  reset: () => j<any>("/api/admin/reset", { method: "POST" }),
  investigate: (t: string, alertId: string, mode: string) =>
    j<{ job_id: string }>(`/api/${t}/alerts/${alertId}/investigate?mode=${mode}`, { method: "POST" }),
  stream(jobId: string, onEvent: (e: TraceEvent) => void): () => void {
    const es = new EventSource(`/api/jobs/${jobId}/events`);
    es.onmessage = (m) => {
      const e = JSON.parse(m.data) as TraceEvent;
      onEvent(e);
      if (e.type === "end") es.close();
    };
    es.onerror = () => es.close();
    return () => es.close();
  },
};

export const money = (x?: number | null) =>
  x == null ? "" : x >= 1_000_000 ? `$${(x / 1_000_000).toFixed(1)}M` : x >= 1000 ? `$${(x / 1000).toFixed(1)}k` : `$${Math.round(x)}`;

export const AGENT_LABEL: Record<string, string> = {
  orchestrator: "Orchestrator", triage: "Triage agent", investigator: "Investigator", sar_writer: "SAR writer",
  reviewer: "Reviewer",
};
