import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Status } from "./types";
import { Investigate } from "./views/Investigate";
import { Cases } from "./views/Cases";
import { Memory } from "./views/Memory";
import { Consortium } from "./views/Consortium";
import { Benchmark } from "./views/Benchmark";
import { Model } from "./views/Model";

type View = "investigate" | "cases" | "memory" | "consortium" | "benchmark" | "model";
const VIEWS: { id: View; label: string; icon: string }[] = [
  { id: "investigate", label: "Investigate", icon: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>' },
  { id: "cases", label: "Cases", icon: '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>' },
  { id: "memory", label: "Memory", icon: '<path d="M12 5a3 3 0 1 0-5.9.8A4 4 0 0 0 4 13a4 4 0 0 0 4 4h1M12 5a3 3 0 1 1 5.9.8A4 4 0 0 1 20 13a4 4 0 0 1-4 4h-1M12 5v14"/>' },
  { id: "consortium", label: "Consortium", icon: '<circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="12" cy="18" r="3"/><path d="M8.5 7.5 10.5 15.5M15.5 7.5 13.5 15.5M9 6h6"/>' },
  { id: "benchmark", label: "Benchmark", icon: '<path d="M3 3v18h18M7 15l4-4 3 3 5-6"/>' },
  { id: "model", label: "Model", icon: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5M3 12c0 1.7 4 3 9 3s9-1.3 9-3"/>' },
];

function Icon({ d }: { d: string }) {
  return <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" dangerouslySetInnerHTML={{ __html: d }} />;
}

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [tenant, setTenant] = useState("alpha");
  const [view, setView] = useState<View>("investigate");
  const [overview, setOverview] = useState<any>(null);
  const [version, setVersion] = useState(0);
  const [focusCase, setFocusCase] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let timer: number | undefined;
    const poll = () => api.status()
      .then((s) => { setStatus(s); setError(null); if (!s.ready) timer = window.setTimeout(poll, 3000); })
      .catch((e) => { setError(String(e)); timer = window.setTimeout(poll, 4000); });
    poll();
    return () => window.clearTimeout(timer);
  }, []);
  const ready = !!status?.ready;
  const refresh = useCallback(() => {
    setVersion((v) => v + 1);
    api.overview(tenant).then(setOverview).catch(() => undefined);
  }, [tenant]);
  useEffect(() => { if (ready) refresh(); }, [tenant, refresh, ready]);

  const reset = async () => {
    if (!confirm("Regenerate both synthetic banks and clear all Hound cases? (analyst history is restored)")) return;
    setBusy(true);
    try { await api.reset(); } finally { setBusy(false); refresh(); }
  };

  const nodeCount = overview?.nodeCount, relCount = overview?.relCount;
  const openAlerts = overview?.alerts?.filter((a: any) => ["NEW", "TRIAGED"].includes(a.status)).reduce((s: number, a: any) => s + a.n, 0);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="logo" aria-hidden>
            <svg viewBox="0 0 64 64" width="22" height="22"><path d="M14 42c0-11 8-20 18-20s18 9 18 20" stroke="#0b0f17" strokeWidth="6" fill="none" strokeLinecap="round" /><circle cx="25" cy="35" r="3.6" fill="#0b0f17" /><circle cx="39" cy="35" r="3.6" fill="#0b0f17" /></svg>
          </div>
          <div>
            <div className="brand-name">Hound <span className="brand-tag">AML</span></div>
            <div className="brand-sub">AML investigations that follow the money through FalkorDB</div>
          </div>
        </div>
        <nav className="nav">
          {VIEWS.map((v) => <button key={v.id} className={view === v.id ? "on" : ""} onClick={() => setView(v.id)}><Icon d={v.icon} />{v.label}</button>)}
        </nav>
        <div className="top-right">
          <select value={tenant} onChange={(e) => { setTenant(e.target.value); setFocusCase(null); }} className="tenant">
            {(status?.tenants ?? [{ id: "alpha", name: "Alpha Bank (synthetic)" }]).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <span className={`pill ${status?.falkordb ? "ok" : "bad"}`} title={status?.graphs.join(", ")}><i className="dot" />
            FalkorDB {status?.falkordb_version ? `${Math.floor(status.falkordb_version / 10000)}.${Math.floor((status.falkordb_version % 10000) / 100)}.${status.falkordb_version % 100}` : ""} · {status?.graphs.length ?? 0} graphs
          </span>
          <span className={`pill ${status?.llm ? "info" : "neutral"}`}><i className="dot" />{status?.llm ? status.model : "Offline playbook mode"}</span>
          <button className="ghost" onClick={reset} disabled={busy}>{busy ? "Resetting…" : "Reset"}</button>
        </div>
      </header>
      {overview && (
        <div className="statbar">
          <span className="live"><i className="dot" /> live graph</span>
          <span><b>{nodeCount?.toLocaleString()}</b> nodes</span>
          <span><b>{relCount?.toLocaleString()}</b> relationships</span>
          <span><b>{overview.relTypes?.TRANSFER?.toLocaleString()}</b> transfers</span>
          <span><b>{openAlerts ?? 0}</b> open alerts in <b>{overview.alert_groups}</b> triage groups</span>
          <span><b>{overview.memory.evidence}</b> evidence · <b>{overview.memory.findings}</b> findings · <b>{overview.memory.lessons}</b> lessons · <b>{overview.memory.runs}</b> agent runs in memory</span>
          <span className="muted">graph <code>{overview.graph}</code></span>
        </div>
      )}
      {error && <div className="banner bad">Cannot reach the Hound API: {error}</div>}
      {!ready ? (
        <main className="main">
          <div className="empty">
            <div className="empty-title pulse">Generating two synthetic banks in FalkorDB…</div>
            <div className="empty-body">Loading accounts, transfers and ownership, running PageRank, betweenness, label propagation and WCC,
              then the monitoring rules and triage. About a minute on a free server; this page opens by itself.</div>
          </div>
        </main>
      ) : (
      <main className="main">
        {view === "investigate" && <Investigate tenant={tenant} llm={!!status?.llm} onChanged={refresh} focusAlert={focusCase} />}
        {view === "cases" && <Cases tenant={tenant} version={version} onOpen={(id) => { setFocusCase(id); setView("investigate"); }} />}
        {view === "memory" && <Memory tenant={tenant} version={version} />}
        {view === "consortium" && <Consortium version={version} graphs={status?.graphs ?? []} />}
        {view === "benchmark" && <Benchmark version={version} />}
        {view === "model" && <Model />}
      </main>
      )}
    </div>
  );
}
