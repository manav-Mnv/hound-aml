import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Cypher, Empty } from "../components/bits";

export function Model() {
  const [s, setS] = useState<any>(null);
  useEffect(() => { api.schema().then(setS); }, []);
  if (!s) return <Empty title="Loading…" />;
  return (
    <div className="bench">
      <div className="view-head">
        <h2>Graph model, rules and agent tools</h2>
        <p className="muted">Everything the agents know and do is in FalkorDB. Reads run through <code>GRAPH.RO_QUERY</code>,
          so a custom query from the model can never write. Writes (findings, cases, lessons) go through typed tools.</p>
      </div>
      <div className="model-grid">
        <div className="card">
          <div className="eyebrow">Node labels</div>
          <div className="chips">{s.labels.map((l: string) => <Badge key={l} tone="info">{l}</Badge>)}</div>
          <div className="eyebrow" style={{ marginTop: 12 }}>Relationship types</div>
          <div className="chips">{s.relationships.map((l: string) => <Badge key={l}>{l}</Badge>)}</div>
        </div>
        <div className="card">
          <div className="eyebrow">Investigator tools ({s.tools.length})</div>
          <ul className="tool-list">
            {s.tools.map((t: any) => (
              <li key={t.name}><code>{t.name}</code> {t.kind === "write" && <Badge tone="warn">write</Badge>} <span className="muted">{t.description.split(". ")[0]}.</span></li>
            ))}
          </ul>
        </div>
      </div>
      <div className="eyebrow" style={{ marginTop: 16 }}>Transaction monitoring rules (Cypher)</div>
      <div className="rules">
        {Object.entries(s.rules).map(([code, q]: [string, any]) => (
          <div key={code} className="card"><div className="pb-title">{code}</div><Cypher code={q} /></div>
        ))}
      </div>
    </div>
  );
}
