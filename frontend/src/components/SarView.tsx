import type { CaseDetail } from "../types";
import { Badge, Empty } from "./bits";

interface Props {
  sar: CaseDetail["sar"];
  onCite: (evidenceId: string) => void;
}

export function SarView({ sar, onCite }: Props) {
  if (!sar) return <Empty title="No SAR draft">A SAR is drafted automatically when the investigator escalates.</Empty>;
  const doc = sar.narrative;
  const review = sar.review;
  return (
    <div className="sar">
      <div className="sar-head">
        <div>
          <div className="sar-title">{doc.title}</div>
          <div className="muted small">{sar.id} · {sar.status} · drafted by {sar.mode === "llm" ? "Claude" : "template"}</div>
        </div>
        {review && (
          <div className={`grounding ${review.issues.length ? "warn" : "ok"}`} title="Share of sentences whose citations exist and contain every amount quoted">
            <b>{Math.round(review.score * 100)}%</b>
            <span>grounded</span>
          </div>
        )}
      </div>
      {doc.typologies?.length > 0 && (
        <div className="chips">{doc.typologies.map((t) => <Badge key={t} tone="danger">{t.replace(/_/g, " ").toLowerCase()}</Badge>)}</div>
      )}
      {doc.sections.map((sec) => (
        <section key={sec.heading} className="sar-section">
          <h4>{sec.heading}</h4>
          <p>
            {sec.sentences.map((s, i) => (
              <span key={i} className="sar-sentence">
                {s.text}{" "}
                {s.evidence_ids.map((id) => (
                  <button key={id} className="cite" onClick={() => onCite(id)} title="Show the query and subgraph behind this sentence">
                    {id.replace("EV-", "")}
                  </button>
                ))}{" "}
              </span>
            ))}
          </p>
        </section>
      ))}
      {review && review.issues.length > 0 && (
        <div className="review-issues">
          <b>Reviewer flagged</b>
          <ul>{review.issues.map((i, k) => <li key={k}>[{i.section}] {i.problems.join("; ")}</li>)}</ul>
        </div>
      )}
    </div>
  );
}
