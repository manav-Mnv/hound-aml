import type { TraceEvent } from "../types";
import { AgentChip, Badge, Collapse, Cypher, IdChip, dispositionLabel, dispositionTone } from "./bits";

interface Props {
  events: TraceEvent[];
  selected?: string | null;
  onSelectEvidence: (id: string) => void;
}

export function Trace({ events, selected, onSelectEvidence }: Props) {
  const visible = events.filter((e) => !["tool_call", "end", "brief"].includes(e.type));
  return (
    <div className="trace">
      {visible.map((e) => <TraceItem key={e.seq} e={e} selected={selected} onSelectEvidence={onSelectEvidence} />)}
    </div>
  );
}

function TraceItem({ e, selected, onSelectEvidence }: { e: TraceEvent; selected?: string | null; onSelectEvidence: (id: string) => void }) {
  switch (e.type) {
    case "case_opened":
      return (
        <div className="ti ti-system">
          <AgentChip agent="orchestrator" /> Opened <IdChip id={e.case_id!} />
          {e.group && e.group.length > 1 && <> · triage grouped <b>{e.group.length}</b> related alerts</>}
        </div>
      );
    case "agent_done":
      return (
        <div className="ti">
          <AgentChip agent={e.agent} /> {e.text}
          {e.reasons && <ul className="reasons">{e.reasons.slice(0, 8).map((r, i) => <li key={i}>{r}</li>)}</ul>}
        </div>
      );
    case "handoff":
      return (
        <div className="ti ti-handoff">
          <AgentChip agent={e.from} /> <span className="arrow">→</span> <AgentChip agent={e.to} />
          {e.mode && <Badge tone={e.mode === "llm" ? "info" : "neutral"}>{e.mode === "llm" ? "Claude" : "playbook mode"}</Badge>}
          {e.note && <span className="muted"> {e.note}</span>}
        </div>
      );
    case "thinking":
      return <div className="ti ti-thinking"><AgentChip agent={e.agent} /> <span className="think">{e.text}</span></div>;
    case "message":
    case "info":
      return <div className="ti"><AgentChip agent={e.agent} /> {e.text}</div>;
    case "merged":
      return <div className="ti ti-memory"><AgentChip agent="orchestrator" /> {e.text}</div>;
    case "warning":
    case "error":
    case "tool_error":
      return <div className="ti ti-warn"><AgentChip agent={e.agent} /> {e.text ?? `${e.tool}: ${e.error}`}</div>;
    case "evidence":
      return (
        <div className={`ti ti-evidence ${selected === e.evidence_id ? "sel" : ""}`} onClick={() => onSelectEvidence(e.evidence_id!)}>
          <div className="ev-head">
            <span className="tool">{e.tool}</span>
            <IdChip id={e.evidence_id!} />
            <span className="muted">{e.ms} ms</span>
          </div>
          <div className="ev-summary">{e.summary}</div>
          {e.cypher && (
            <Collapse label="Cypher">
              {e.cypher.map((c, i) => <Cypher key={i} code={c} />)}
            </Collapse>
          )}
        </div>
      );
    case "action": {
      const r = e.result ?? {};
      if (e.tool === "record_finding") {
        return (
          <div className={`ti ti-finding ${r.ok ? "" : "bad"}`}>
            <Badge tone={r.ok ? "accent" : "danger"}>finding</Badge>{" "}
            {r.ok ? <>recorded <b>{r.finding_id}</b> citing {r.cited?.join(", ")}</> : r.error}
          </div>
        );
      }
      if (e.tool === "consolidate_alerts") {
        return (
          <div className="ti ti-memory">
            <Badge tone="accent">consolidated</Badge> merged {r.merged_alerts?.length ?? 0} alert(s) and {r.accounts_added?.length ?? 0} account(s) into this case
          </div>
        );
      }
      if (e.tool === "remember") return <div className="ti ti-memory"><Badge tone="violet">memory</Badge> saved lesson {r.lesson_id}</div>;
      if (e.tool === "submit_disposition") return null;
      return <div className="ti">{e.tool}</div>;
    }
    case "disposition": {
      const d = e.disposition ?? {};
      return (
        <div className="ti ti-disposition">
          <AgentChip agent="investigator" /> <Badge tone={dispositionTone(d.disposition)}>{dispositionLabel(d.disposition)}</Badge>
          <span className="muted"> risk {Math.round(d.risk_score ?? 0)}</span>
          <div className="rationale">{d.rationale}</div>
        </div>
      );
    }
    case "sar_draft":
      return <div className="ti"><AgentChip agent="sar_writer" /> Drafted SAR narrative{e.revision ? " (revision)" : ""}: {e.sar?.sections?.length} sections</div>;
    case "review": {
      const r = e.review!;
      return (
        <div className={`ti ${r.issues.length ? "ti-warn" : "ti-ok"}`}>
          <AgentChip agent="reviewer" /> {r.grounded}/{r.sentences} sentences grounded in cited evidence
          {r.issues.length > 0 && <ul className="reasons">{r.issues.slice(0, 4).map((i, k) => <li key={k}>{i.problems.join("; ")}</li>)}</ul>}
        </div>
      );
    }
    case "case_done":
      return <div className="ti ti-system"><AgentChip agent="orchestrator" /> Case ready for human review</div>;
    default:
      return null;
  }
}
