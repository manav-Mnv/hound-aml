import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { Alert, CaseDetail, Evidence, Subgraph, TraceEvent } from "../types";
import { GraphCanvas, Legend, mergeGraphs } from "../components/GraphCanvas";
import { Trace } from "../components/Trace";
import { SarView } from "../components/SarView";
import { Badge, Collapse, Cypher, Empty, ScoreRing, dispositionLabel, dispositionTone } from "../components/bits";

const EMPTY: Subgraph = { nodes: [], edges: [] };
type Tab = "trace" | "findings" | "sar" | "evidence";

interface Props { tenant: string; llm: boolean; onChanged: () => void; focusAlert?: string | null }

export function Investigate({ tenant, llm, onChanged, focusAlert }: Props) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [filter, setFilter] = useState<"open" | "cases" | "all">("open");
  const [selected, setSelected] = useState<Alert | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [graph, setGraph] = useState<Subgraph>(EMPTY);
  const [highlight, setHighlight] = useState<string[]>([]);
  const [evidenceSel, setEvidenceSel] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("trace");
  const [running, setRunning] = useState(false);
  const [mode, setMode] = useState<"auto" | "offline">(llm ? "auto" : "offline");
  const [note, setNote] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const stopRef = useRef<(() => void) | null>(null);
  const liveEvidence = useRef<Record<string, TraceEvent>>({});

  const loadAlerts = useCallback(() => api.alerts(tenant).then(setAlerts), [tenant]);
  useEffect(() => { loadAlerts(); setSelected(null); setDetail(null); setEvents([]); setGraph(EMPTY); }, [tenant, loadAlerts]);
  useEffect(() => setMode(llm ? "auto" : "offline"), [llm]);

  const groupSizes = useMemo(() => {
    const m: Record<string, number> = {};
    for (const a of alerts) if (a.grp) m[a.grp] = (m[a.grp] ?? 0) + 1;
    return m;
  }, [alerts]);

  const shown = alerts.filter((a) =>
    filter === "all" ? true : filter === "open" ? !a.case_id : !!a.case_id);

  const loadCase = useCallback(async (caseId: string, keepEvents = false) => {
    const d = await api.case(tenant, caseId);
    setDetail(d);
    let g = EMPTY;
    for (const e of d.evidence) g = mergeGraphs(g, e.graph);
    setGraph(g);
    if (!keepEvents) setEvents(detailToEvents(d));
    if (d.sar) setTab("sar");
    return d;
  }, [tenant]);

  const selectAlert = useCallback(async (a: Alert) => {
    stopRef.current?.();
    setSelected(a); setHighlight([]); setEvidenceSel(null); setRunning(false); setNote("");
    if (a.case_id) {
      setTab("trace");
      await loadCase(a.case_id);
    } else {
      setDetail(null); setEvents([]); setTab("trace");
      const nb = await api.neighborhood(tenant, a.account);
      nb.nodes = nb.nodes.map((n) => (n.id === a.account ? { ...n, focus: true, alert: true } : n));
      setGraph(nb);
    }
  }, [tenant, loadCase]);

  useEffect(() => {
    if (!focusAlert || !alerts.length) return;
    const a = alerts.find((x) => x.id === focusAlert || x.case_id === focusAlert);
    if (a) selectAlert(a);
  }, [focusAlert, alerts, selectAlert]);

  const investigate = async () => {
    if (!selected) return;
    setRunning(true); setEvents([]); setDetail(null); setTab("trace"); liveEvidence.current = {};
    const base = await api.neighborhood(tenant, selected.account);
    base.nodes = base.nodes.filter((n) => n.id === selected.account || n.kind === "Person" || n.kind === "Company")
      .map((n) => (n.id === selected.account ? { ...n, focus: true, alert: true } : n));
    base.edges = base.edges.filter((e) => base.nodes.some((n) => n.id === e.source) && base.nodes.some((n) => n.id === e.target));
    setGraph(base);
    const { job_id } = await api.investigate(tenant, selected.id, mode);
    let caseId: string | null = null;
    stopRef.current = api.stream(job_id, (e) => {
      setEvents((prev) => [...prev, e]);
      if (e.type === "case_opened" || e.type === "merged") caseId = e.case_id ?? null;
      if (e.type === "evidence" && e.graph) {
        liveEvidence.current[e.evidence_id!] = e;
        setGraph((g) => mergeGraphs(g, e.graph!));
        setHighlight(e.graph.nodes.map((n) => n.id));
      }
      if (e.type === "end") {
        setRunning(false);
        setHighlight([]);
        loadAlerts();
        onChanged();
        if (caseId) loadCase(caseId, true);
      }
    });
  };

  const selectEvidence = (id: string) => {
    setEvidenceSel(id);
    setTab("evidence");
    const ev = detail?.evidence.find((x) => x.id === id) ?? (liveEvidence.current[id] as any);
    if (ev?.graph) setHighlight(ev.graph.nodes.map((n: any) => n.id));
  };

  const decide = async (decision: string) => {
    if (!detail) return;
    const r = await api.decide(tenant, detail.case.id, decision, note);
    setToast(
      decision === "approve_sar"
        ? `SAR filed. ${r.published_to_consortium.length} hashed identifier(s) shared with the consortium.${r.lesson_id ? " Your note was saved as a lesson." : ""}`
        : `Decision recorded.${r.lesson_id ? " Your note was saved to memory as a lesson for future cases." : ""}`,
    );
    setTimeout(() => setToast(null), 6000);
    setNote("");
    await loadCase(detail.case.id, true);
    loadAlerts();
    onChanged();
  };

  const evidenceList: Evidence[] = detail?.evidence ??
    Object.values(liveEvidence.current).map((e) => ({ id: e.evidence_id!, tool: e.tool!, summary: e.summary!, cypher: (e.cypher ?? []).join("\n\n"), params: "", ms: e.ms ?? 0, rows: 0, graph: e.graph! }));
  const ev = evidenceList.find((e) => e.id === evidenceSel);
  const c = detail?.case;
  const kinds = [...new Set(graph.nodes.map((n) => n.kind))];

  return (
    <div className="investigate">
      <aside className="queue">
        <div className="queue-head">
          <div className="seg">
            {(["open", "cases", "all"] as const).map((f) => (
              <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
                {f === "open" ? `Open ${alerts.filter((a) => !a.case_id).length}` : f === "cases" ? `In cases ${alerts.filter((a) => a.case_id).length}` : `All ${alerts.length}`}
              </button>
            ))}
          </div>
        </div>
        <div className="queue-list">
          {shown.map((a) => (
            <button key={a.id} className={`alert-row ${selected?.id === a.id ? "sel" : ""}`} onClick={() => selectAlert(a)}>
              <ScoreRing score={a.score} />
              <div className="alert-main">
                <div className="alert-top">
                  <span className="holder">{a.holder}</span>
                  {a.disposition && <Badge tone={dispositionTone(a.disposition)}>{dispositionLabel(a.disposition)}</Badge>}
                </div>
                <div className="alert-rule">{a.rule} · {a.rule_name}</div>
                <div className="alert-desc">{a.description}</div>
                {a.grp && groupSizes[a.grp] > 1 && <span className="group-chip">{groupSizes[a.grp]} related alerts</span>}
              </div>
            </button>
          ))}
          {!shown.length && <Empty title="Nothing here">Switch filters or run triage.</Empty>}
        </div>
      </aside>

      <section className="stage">
        {selected ? (
          <div className="case-bar">
            <div className="case-id">
              <div className="eyebrow">{c ? c.id : selected.id}</div>
              <div className="case-title">{selected.holder} <span className="muted">· {selected.account}</span></div>
            </div>
            <div className="case-meta">
              {c?.disposition && <Badge tone={dispositionTone(c.disposition)}>{dispositionLabel(c.disposition)}</Badge>}
              {c?.risk_score != null && <span className="muted">risk {Math.round(c.risk_score)}</span>}
              {c && <span className="muted">{c.alerts.length} alert(s) · {c.accounts.length} account(s) · {detail?.evidence.length} evidence</span>}
              {!c && !running && (
                <>
                  <select value={mode} onChange={(e) => setMode(e.target.value as any)} className="mode">
                    {llm && <option value="auto">Claude Opus 5.5</option>}
                    <option value="offline">Offline playbook</option>
                  </select>
                  <button className="primary" onClick={investigate}>Investigate with Hound</button>
                </>
              )}
              {running && <span className="pulse">Investigating…</span>}
            </div>
          </div>
        ) : (
          <div className="case-bar"><div className="case-title muted">Pick an alert from the queue. Highest triage scores first.</div></div>
        )}
        <div className="canvas-wrap">
          {graph.nodes.length ? (
            <GraphCanvas graph={graph} highlight={highlight} onSelect={(id) => setHighlight([id])} />
          ) : (
            <Empty title="Graph context appears here">Each tool call adds the subgraph it read, so you can watch the agent follow the money.</Empty>
          )}
          {kinds.length > 0 && <Legend kinds={kinds} />}
          {highlight.length > 0 && <button className="clear-hl" onClick={() => setHighlight([])}>Show all</button>}
        </div>
        {c && (c.status === "PENDING_APPROVAL" || c.disposition === "FALSE_POSITIVE") && c.origin === "hound" && (
          <div className="decision-bar">
            <input placeholder="Analyst note (saved to memory as a lesson)…" value={note} onChange={(e) => setNote(e.target.value)} />
            {c.status === "PENDING_APPROVAL" ? (
              <>
                <button className="danger" onClick={() => decide("approve_sar")}>Approve & file SAR</button>
                <button onClick={() => decide("reject_sar")}>Override: not suspicious</button>
              </>
            ) : (
              <button onClick={() => decide("reopen_escalate")}>Override: escalate</button>
            )}
          </div>
        )}
        {toast && <div className="toast">{toast}</div>}
      </section>

      <aside className="panel">
        <div className="tabs">
          {(["trace", "findings", "sar", "evidence"] as Tab[]).map((t) => (
            <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
              {t === "trace" ? "Agent trace" : t === "findings" ? `Findings ${detail?.findings.length ?? ""}` : t === "sar" ? "SAR" : "Evidence"}
            </button>
          ))}
        </div>
        <div className="panel-body">
          {tab === "trace" && (
            selected ? (
              events.length ? <Trace events={events} selected={evidenceSel} onSelectEvidence={selectEvidence} /> :
                <AlertPreview a={selected} />
            ) : <Empty title="No alert selected" />
          )}
          {tab === "findings" && (
            detail?.findings.length ? (
              <div className="findings">
                {detail.findings.map((f) => (
                  <div key={f.id} className={`finding sev-${f.severity} ${f.typology === "BENIGN_EXPLANATION" ? "benign" : ""}`}>
                    <div className="finding-head">
                      <Badge tone={f.typology === "BENIGN_EXPLANATION" ? "ok" : f.severity === "critical" || f.severity === "high" ? "danger" : "warn"}>
                        {f.typology.replace(/_/g, " ").toLowerCase()}
                      </Badge>
                      <span className="muted small">{f.severity} · {Math.round(f.confidence * 100)}%</span>
                    </div>
                    <div>{f.claim}</div>
                    <div className="cites">{f.evidence.map((id) => <button key={id} className="cite" onClick={() => selectEvidence(id)}>{id.replace("EV-", "")}</button>)}</div>
                  </div>
                ))}
                {detail.runs.length > 0 && <AgentRuns detail={detail} />}
              </div>
            ) : <Empty title="No findings yet" />
          )}
          {tab === "sar" && <SarView sar={detail?.sar ?? null} onCite={selectEvidence} />}
          {tab === "evidence" && (
            ev ? (
              <div className="evidence-detail">
                <div className="ev-head"><span className="tool">{ev.tool}</span><span className="ev-id">{ev.id}</span><span className="muted">{ev.ms} ms</span></div>
                <p>{ev.summary}</p>
                <div className="eyebrow">Cypher executed on FalkorDB</div>
                <Cypher code={ev.cypher} />
                {ev.params && <Collapse label="Parameters"><pre className="params">{ev.params}</pre></Collapse>}
              </div>
            ) : (
              <div className="ev-list">
                {evidenceList.map((e) => (
                  <button key={e.id} className="ev-item" onClick={() => selectEvidence(e.id)}>
                    <span className="tool">{e.tool}</span> <span className="ev-id">{e.id}</span>
                    <div className="ev-summary">{e.summary}</div>
                  </button>
                ))}
                {!evidenceList.length && <Empty title="No evidence yet" />}
              </div>
            )
          )}
        </div>
      </aside>
    </div>
  );
}

function AlertPreview({ a }: { a: Alert }) {
  return (
    <div className="alert-preview">
      <div className="eyebrow">{a.id}</div>
      <h3>{a.rule_name}</h3>
      <p>{a.description}</p>
      <div className="eyebrow">Why triage scored it {a.score}</div>
      <ul className="reasons">{(a.reasons ?? []).map((r, i) => <li key={i}>{r}</li>)}</ul>
      <p className="muted small">Click <b>Investigate with Hound</b> to hand this alert to the investigator agent.
        It reads its playbook and lessons from the graph, runs Cypher tools, records findings with evidence, and decides.</p>
    </div>
  );
}

function AgentRuns({ detail }: { detail: CaseDetail }) {
  return (
    <div className="runs">
      <div className="eyebrow">Agent runs (stored in the graph)</div>
      {detail.runs.map((r) => (
        <div key={r.id} className="run">
          <span className={`agent-chip agent-${r.agent}`}>{r.agent}</span>
          <span className="muted small">{r.mode} · {r.model}{r.tool_calls ? ` · ${r.tool_calls} tool calls` : ""}
            {r.input_tokens ? ` · ${Math.round((r.input_tokens + (r.output_tokens ?? 0)) / 1000)}k tokens` : ""} · {r.status}</span>
        </div>
      ))}
    </div>
  );
}

function detailToEvents(d: CaseDetail): TraceEvent[] {
  const out: TraceEvent[] = [];
  let seq = 0;
  for (const r of d.runs) {
    out.push({ seq: seq++, t: 0, type: "handoff", from: r.agent, to: r.handoffs.find((h) => h.to)?.to ?? undefined, mode: r.mode, note: r.status });
  }
  for (const e of d.evidence) {
    out.push({ seq: seq++, t: 0, type: "evidence", tool: e.tool, evidence_id: e.id, summary: e.summary, cypher: [e.cypher], ms: e.ms, graph: e.graph });
  }
  if (d.case.disposition) {
    out.push({ seq: seq++, t: 0, type: "disposition", disposition: { disposition: d.case.disposition, risk_score: d.case.risk_score, rationale: d.case.summary } });
  }
  if (d.sar?.review) out.push({ seq: seq++, t: 0, type: "review", review: d.sar.review });
  return out.filter((e) => e.type !== "handoff" || e.to);
}

