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
const VIEWS: { id: View; label: string }[] = [
  { id: "investigate", label: "Investigate" }, { id: "cases", label: "Cases" }, { id: "memory", label: "Memory" },
  { id: "consortium", label: "Consortium" }, { id: "benchmark", label: "Benchmark" }, { id: "model", label: "Model" },
];

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
          <div className="logo">H</div>
          <div>
            <div className="brand-name">Hound</div>
            <div className="brand-sub">AML investigations that follow the money through FalkorDB</div>
          </div>
        </div>
        <nav className="nav">
          {VIEWS.map((v) => <button key={v.id} className={view === v.id ? "on" : ""} onClick={() => setView(v.id)}>{v.label}</button>)}
        </nav>
        <div className="top-right">
          <select value={tenant} onChange={(e) => { setTenant(e.target.value); setFocusCase(null); }} className="tenant">
            {(status?.tenants ?? [{ id: "alpha", name: "Alpha Bank (synthetic)" }]).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <span className={`pill ${status?.falkordb ? "ok" : "bad"}`} title={status?.graphs.join(", ")}>
            FalkorDB {status?.falkordb_version ? `${Math.floor(status.falkordb_version / 10000)}.${Math.floor((status.falkordb_version % 10000) / 100)}.${status.falkordb_version % 100}` : ""} · {status?.graphs.length ?? 0} graphs
          </span>
          <span className={`pill ${status?.llm ? "info" : "neutral"}`}>{status?.llm ? status.model : "Offline playbook mode"}</span>
          <button className="ghost" onClick={reset} disabled={busy}>{busy ? "Resetting…" : "Reset"}</button>
        </div>
      </header>
      {overview && (
        <div className="statbar">
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
