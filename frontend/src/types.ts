export type Kind =
  | "Person" | "Company" | "Account" | "External" | "Sanctioned" | "Blocked" | "Device" | "IP" | "Phone"
  | "Email" | "Address" | "Branch" | "Case" | "Lesson" | "Signal" | "AgentRun" | "Finding" | "SAR" | "Alert"
  | "Playbook" | string;

export interface GNode { id: string; kind: Kind; label: string; country?: string; focus?: boolean; alert?: boolean; [k: string]: unknown }
export interface GEdge { id: string; source: string; target: string; rel: string; amount?: number; pct?: number; ts?: number; [k: string]: unknown }
export interface Subgraph { nodes: GNode[]; edges: GEdge[] }

export interface Tenant { id: string; name: string }
export interface Status {
  falkordb: boolean; falkordb_version: number | null; graphs: string[]; llm: boolean; model: string; tenants: Tenant[]; ready: boolean;
}

export interface Alert {
  id: string; rule: string; rule_name: string; typology: string; description: string; status: string;
  score: number | null; reasons: string[] | null; grp: string | null; account: string; party: string; holder: string;
  party_type: string; case_id: string | null; disposition: string | null;
}

export interface Evidence {
  id: string; tool: string; summary: string; cypher: string; params: string; ms: number; rows: number; graph: Subgraph;
}
export interface Finding { id: string; typology: string; claim: string; severity: string; confidence: number; evidence: string[] }
export interface AgentRunRow {
  id: string; agent: string; model: string; mode: string; status: string; started: number; ended: number | null;
  input_tokens: number | null; output_tokens: number | null; tool_calls: number | null; handoffs: { to: string | null; note: string | null }[];
}
export interface SarSentence { text: string; evidence_ids: string[] }
export interface SarSection { heading: string; sentences: SarSentence[] }
export interface SarDoc {
  title: string; subjects: string[]; typologies: string[]; activity_start: string; activity_end: string;
  total_suspicious_amount: number; sections: SarSection[];
}
export interface Review { sentences: number; grounded: number; score: number; issues: { section: string; text: string; problems: string[] }[] }
export interface CaseDetail {
  case: {
    id: string; status: string; disposition: string | null; summary: string | null; typologies: string[] | null;
    risk_score: number | null; actions: string[] | null; opened: number; origin: string;
    subjects: { id: string; name: string; type: string }[]; accounts: string[];
    alerts: { id: string; rule: string; merged: boolean | null; reason: string | null }[];
  };
  findings: Finding[]; evidence: Evidence[]; runs: AgentRunRow[];
  sar: { id: string; status: string; title: string; narrative: SarDoc; review: Review | null; grounding: number; mode: string } | null;
}

export interface TraceEvent {
  seq: number; t: number; type: string; agent?: string; text?: string; tool?: string; args?: Record<string, unknown>;
  evidence_id?: string; summary?: string; cypher?: string[]; ms?: number; graph?: Subgraph; result?: any;
  from?: string; to?: string; mode?: string; case_id?: string; disposition?: any; sar?: SarDoc; review?: Review;
  revision?: number; reasons?: string[]; alert?: Alert; group?: Alert[]; note?: string; error?: string;
}
