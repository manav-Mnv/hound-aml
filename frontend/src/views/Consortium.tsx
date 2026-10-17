import { useEffect, useState } from "react";
import { api } from "../api";
import type { Subgraph } from "../types";
import { GraphCanvas } from "../components/GraphCanvas";
import { Badge, Empty, IdChip } from "../components/bits";
import { humanize } from "../format";

export function Consortium({ version, graphs }: { version: number; graphs: string[] }) {
  const [data, setData] = useState<any>(null);
  useEffect(() => { api.consortium().then(setData); }, [version]);
  if (!data) return <Empty title="Loading consortium…" />;
  const graph: Subgraph = { nodes: [], edges: [] };
  const insts = new Set<string>();
  for (const s of data.signals) {
    if (!insts.has(s.institution)) {
      insts.add(s.institution);
      graph.nodes.push({ id: s.institution, kind: "Company", label: s.name });
    }
    graph.nodes.push({ id: s.hash, kind: "Signal", label: `${s.kind} ${s.hash.slice(0, 8)}…` });
    graph.edges.push({ id: `${s.institution}-${s.hash}`, source: s.institution, target: s.hash, rel: "REPORTED" });
  }
  return (
    <div className="split">
      <div className="split-main">
        <div className="view-head">
          <h2>Cross-bank consortium</h2>
          <p className="muted">One FalkorDB instance holds an isolated graph per bank and a shared consortium graph. Banks never
            see each other's customers: only keyed hashes (HMAC-SHA256) of risky identifiers are published, the way FinCEN's
            section 314(b) program lets institutions share information about suspected money laundering and fraud.
            When Alpha's investigator checks a mule's phone, the hash matches what Beta Credit Union reported in September.</p>
          <div className="chips">{graphs.map((g) => <Badge key={g} tone={g.endsWith("consortium") ? "violet" : "info"}>{g}</Badge>)}</div>
        </div>
        <div className="canvas-wrap">{graph.nodes.length ? <GraphCanvas graph={graph} /> : <Empty title="No signals shared yet" />}</div>
      </div>
      <aside className="split-side">
        <div className="eyebrow">Signals in {data.graph}</div>
        <table className="table">
          <thead><tr><th>Reported by</th><th>Kind</th><th>Hash</th><th>Typology</th><th>Case</th></tr></thead>
          <tbody>
            {data.signals.map((s: any) => (
              <tr key={s.hash + s.institution}>
                <td>{s.name}</td><td>{s.kind}</td><td className="mono nowrap" title={s.hash}>{s.hash.slice(0, 10)}…</td><td>{humanize(s.typology)}</td><td>{s.case_ref && <IdChip id={s.case_ref} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </aside>
    </div>
  );
}
