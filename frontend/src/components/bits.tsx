import { useState, type ReactNode } from "react";
import { AGENT_LABEL } from "../api";
import { idTone, splitId } from "../format";

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

export function ScoreRing({ score, size = 40 }: { score: number | null; size?: number }) {
  const s = Math.max(0, Math.min(100, score ?? 0));
  const tone = s >= 60 ? "var(--danger)" : s >= 35 ? "var(--warn)" : "var(--ok)";
  const r = 15.5, c = 2 * Math.PI * r;
  return (
    <div className="score-ring" style={{ width: size, height: size }} title={`Triage score ${Math.round(s)} / 100`}>
      <svg viewBox="0 0 36 36" width={size} height={size}>
        <circle cx="18" cy="18" r={r} className="track" />
        <circle cx="18" cy="18" r={r} className="bar" stroke={tone} strokeDasharray={`${(s / 100) * c} ${c}`} transform="rotate(-90 18 18)" />
      </svg>
      <span style={{ color: tone }}>{Math.round(s)}</span>
    </div>
  );
}

/** An identifier (AC-308899, ALR-R4-308899, CASE-2026-0007, EV-...) as a two-tone mono chip. */
export function IdChip({ id, onClick, title }: { id: string; onClick?: () => void; title?: string }) {
  const [pre, rest] = splitId(id);
  const body = <>{pre && <span className="id-pre">{pre}</span>}<span className="id-num">{rest}</span></>;
  const cls = `id-chip id-${idTone(id)}`;
  return onClick
    ? <button className={cls} onClick={(e) => { e.stopPropagation(); onClick(); }} title={title ?? id}>{body}</button>
    : <span className={cls} title={title ?? id}>{body}</span>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      {children && <div className="empty-body">{children}</div>}
    </div>
  );
}
