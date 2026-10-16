import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Empty } from "../components/bits";

export function Benchmark({ version }: { version: number }) {
  const [evals, setEvals] = useState<Record<string, any> | null>(null);
  useEffect(() => { api.evals().then(setEvals); }, [version]);
  if (!evals) return <Empty title="Loading…" />;
  const keys = Object.keys(evals);
  if (!keys.length) return <Empty title="No benchmark yet">Run <code>uv run hound eval</code> in backend/.</Empty>;
  const r = evals[keys.find((k) => k.endsWith("auto")) ?? keys[0]];
  const h = r.hound;
  const reviewed = h.investigations_run;
  return (
    <div className="bench">
      <div className="view-head">
        <h2>Rules alone vs. Hound</h2>
        <p className="muted">Synthetic benchmark on {r.tenant === "alpha" ? "Alpha Bank" : r.tenant}: {r.alerts} alerts from six
          threshold rules, five planted laundering schemes, ground truth kept outside the graph. Mode: {r.mode === "auto" ? "Claude Opus 5.5" : "offline playbook runner"}.
          Real-world rule engines run at 90-95% false positives; this dataset is denser by design so every typology is exercised.</p>
      </div>
      <div className="kpis">
        <Kpi label="Alerts from rules" value={r.alerts} sub={`${Math.round(r.rules_only.precision * 100)}% true positives`} />
        <Kpi label="Cases after triage + merge" value={h.cases_opened} sub={`${h.alerts_merged_into_cases} duplicate alerts merged`} />
        <Kpi label="False positives closed with rationale" value={`${h.false_positive_alerts_closed}/${h.false_positive_alerts_total}`} sub="each cites its evidence" tone="ok" />
        <Kpi label="Schemes escalated" value={`${Object.values(r.scenarios).filter((s: any) => s.detected).length}/${Object.keys(r.scenarios).length}`} sub={`${h.false_sar_cases.length} false SAR cases`} tone="danger" />
        <Kpi label="Accounts found that no rule flagged" value={h.accounts_found_without_alerts.length} sub="via graph traversal" tone="violet" />
        <Kpi label="Alert precision / recall" value={`${Math.round(h.alert_precision * 100)}% / ${Math.round(h.alert_recall * 100)}%`} sub={`${reviewed} investigations in ${r.seconds}s`} />
      </div>
      <table className="table">
        <thead><tr><th>Planted scheme</th><th>Escalated</th><th>Accounts in case</th><th>Case</th></tr></thead>
        <tbody>
          {Object.entries(r.scenarios).map(([k, s]: [string, any]) => (
            <tr key={k}>
              <td><b>{k}</b> <span className="muted">{s.title}</span></td>
              <td>{s.detected ? <Badge tone="danger">yes</Badge> : <Badge>missed</Badge>}</td>
              <td>{s.accounts_found}/{s.accounts_total}</td>
              <td className="mono small">{s.cases.join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">Reproduce: <code>cd backend && uv run hound seed && uv run hound eval --mode offline</code> (or <code>--mode auto</code> with an Anthropic key).</p>
    </div>
  );
}

function Kpi({ label, value, sub, tone }: { label: string; value: any; sub?: string; tone?: string }) {
  return (
    <div className={`kpi tone-${tone ?? "neutral"}`}>
      <div className="kpi-value">{value}</div>
      <div className="kpi-label">{label}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}
