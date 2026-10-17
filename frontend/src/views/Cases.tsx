import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Empty, IdChip, dispositionLabel, dispositionTone } from "../components/bits";

export function Cases({ tenant, version, onOpen }: { tenant: string; version: number; onOpen: (caseId: string) => void }) {
  const [rows, setRows] = useState<any[] | null>(null);
  useEffect(() => { api.cases(tenant).then(setRows); }, [tenant, version]);
  if (!rows) return <Empty title="Loading…" />;
  return (
    <div className="bench">
      <div className="view-head">
        <h2>Cases</h2>
        <p className="muted">Every case is a node in the graph, linked to its alerts, subjects, findings, evidence, agent runs and SAR.
          Historical cases were closed by human analysts before Hound arrived; they are part of its memory.</p>
      </div>
      <table className="table">
        <thead><tr><th>Case</th><th>Disposition</th><th>Typologies</th><th>Subjects</th><th>Alerts</th><th>Origin</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className={r.origin === "hound" ? "clickable" : ""} onClick={() => r.origin === "hound" && onOpen(r.id)}>
              <td><IdChip id={r.id} /></td>
              <td><Badge tone={dispositionTone(r.disposition)}>{dispositionLabel(r.disposition ?? r.status)}</Badge></td>
              <td>{(r.typologies ?? []).join(", ").replace(/_/g, " ").toLowerCase()}</td>
              <td>{(r.subjects ?? []).join(", ")}</td>
              <td>{r.alerts}</td>
              <td>{r.origin === "hound" ? <Badge tone="accent">Hound</Badge> : <Badge>analyst history</Badge>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <Empty title="No cases yet" />}
    </div>
  );
}
