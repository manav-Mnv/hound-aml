import { useState, type ReactNode } from "react";
import { AGENT_LABEL } from "../api";

const KEYWORDS = /\b(MATCH|OPTIONAL|WHERE|RETURN|WITH|UNWIND|CALL|YIELD|ORDER BY|ORDER|BY|LIMIT|AND|OR|NOT|IN|AS|DISTINCT|CASE|WHEN|THEN|ELSE|END|CREATE|MERGE|SET|UNION|ALL|count|sum|collect|reduce|coalesce|size|head|min|max|abs|toFloat|toInteger|nodes|relationships|startNode|endNode|labels|any|range)\b/g;

export function Cypher({ code }: { code: string }) {
  const parts = code.split(/(\/\/.*$|'[^']*'|\$\w+)/gm);
  return (
    <pre className="cypher">
      {parts.map((p, i) => {
        if (!p) return null;
        if (p.startsWith("//")) return <span key={i} className="c-comment">{p}</span>;
        if (p.startsWith("'")) return <span key={i} className="c-str">{p}</span>;
        if (p.startsWith("$")) return <span key={i} className="c-param">{p}</span>;
        const segs = p.split(KEYWORDS);
        return segs.map((s, k) =>
          k % 2 === 1 ? <span key={`${i}-${k}`} className={/^[a-z]/.test(s) ? "c-fn" : "c-kw"}>{s}</span> : <span key={`${i}-${k}`}>{s}</span>,
        );
      })}
    </pre>
  );
}

export function Badge({ children, tone = "neutral", title }: { children: ReactNode; tone?: string; title?: string }) {
  return <span className={`badge tone-${tone}`} title={title}>{children}</span>;
}

export function AgentChip({ agent }: { agent?: string }) {
  if (!agent) return null;
  return <span className={`agent-chip agent-${agent}`}>{AGENT_LABEL[agent] ?? agent}</span>;
}

export function Collapse({ label, children, open = false }: { label: ReactNode; children: ReactNode; open?: boolean }) {
  const [o, setO] = useState(open);
  return (
    <div className="collapse">
      <button className="collapse-toggle" onClick={() => setO(!o)}>{o ? "▾" : "▸"} {label}</button>
      {o && <div className="collapse-body">{children}</div>}
    </div>
  );
}

export function dispositionTone(d?: string | null): string {
  if (!d) return "neutral";
  if (d.includes("SAR")) return "danger";
  if (d.includes("EDD") || d.includes("MONITOR")) return "warn";
  if (d.includes("FALSE")) return "ok";
  return "neutral";
}

export function dispositionLabel(d?: string | null): string {
  return ({
    SAR_RECOMMENDED: "SAR recommended", SAR_FILED: "SAR filed", FALSE_POSITIVE: "Closed: false positive",
    MONITOR_EDD: "Monitor / EDD",
  } as Record<string, string>)[d ?? ""] ?? (d ?? "Open");
}

export function ScoreRing({ score }: { score: number | null }) {
  const s = score ?? 0;
  const tone = s >= 60 ? "#ef4444" : s >= 35 ? "#f59e0b" : "#22c55e";
  return (
    <div className="score-ring" style={{ background: `conic-gradient(${tone} ${s * 3.6}deg, #1f2937 0deg)` }} title={`Triage score ${s}`}>
      <span>{Math.round(s)}</span>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      {children && <div className="empty-body">{children}</div>}
    </div>
  );
}
