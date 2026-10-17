import { useEffect, useState } from "react";
import { api } from "../api";
import type { Subgraph } from "../types";
import { GraphCanvas, KindIcon } from "../components/GraphCanvas";
import { Badge, Empty, IdChip } from "../components/bits";
import { humanize, kindLabel, nodeCaption } from "../format";

export function Memory({ tenant, version }: { tenant: string; version: number }) {
  const [data, setData] = useState<any>(null);
  const [sel, setSel] = useState<any>(null);
  useEffect(() => { api.memory(tenant).then(setData); }, [tenant, version]);
  if (!data) return <Empty title="Loading memory graph…" />;
  const graph: Subgraph = { nodes: data.nodes, edges: data.edges };
  const node = sel && data.nodes.find((n: any) => n.id === sel);
  const playbooks = Object.values(data.playbooks) as any[];
  return (
    <div className="split">
      <div className="split-main">
        <div className="view-head">
          <h2>Agent memory</h2>
          <p className="muted">Cases, findings, agent runs, lessons and playbooks live in the same FalkorDB graph as the
            transactions, attached to the people and accounts they are about. That is how a new investigation recalls an
            analyst's note from August, and how the triage agent knows a payroll processor was already cleared.</p>
        </div>
        <div className="canvas-wrap tall">
          {graph.nodes.length ? <GraphCanvas graph={graph} onSelect={(id) => setSel(id)} modes={false} /> : <Empty title="No memory yet" />}
        </div>
      </div>
      <aside className="split-side">
        {node && (
          <div className="card node-card">
            <div className="eyebrow node-kind"><KindIcon kind={node.kind} /> {kindLabel(node.kind)}</div>
            <h3>{nodeCaption(node).title}</h3>
            <div className="chips"><IdChip id={node.id} />{node.disposition && <Badge tone="info">{humanize(node.disposition)}</Badge>}</div>
            {node.text && <p>{node.text}</p>}
          </div>
        )}
        <div className="eyebrow">Procedural memory: playbooks</div>
        {playbooks.map((pb) => (
          <div key={pb.typology} className="card playbook">
            <div className="pb-title">{pb.typology.replace(/_/g, " ").toLowerCase()}</div>
            <ol>{pb.steps.map((s: any, i: number) => <li key={i}><code>{s.tool}</code> {s.instruction}</li>)}</ol>
            {pb.lessons.length > 0 && (
              <div className="lessons">
                {pb.lessons.map((l: any) => <div key={l.id} className="lesson">“{l.text}” <span className="muted">— {l.author}</span></div>)}
              </div>
            )}
          </div>
        ))}
      </aside>
    </div>
  );
}
