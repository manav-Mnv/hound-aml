import { useEffect, useRef } from "react";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import fcose from "cytoscape-fcose";
import type { GEdge, GNode, Subgraph } from "../types";
import { money } from "../api";

cytoscape.use(fcose);

export const KIND_STYLE: Record<string, { color: string; shape: string; size: number }> = {
  Person: { color: "#60a5fa", shape: "ellipse", size: 30 },
  Company: { color: "#a78bfa", shape: "round-rectangle", size: 32 },
  Account: { color: "#94a3b8", shape: "round-rectangle", size: 26 },
  External: { color: "#f59e0b", shape: "diamond", size: 30 },
  Sanctioned: { color: "#ef4444", shape: "octagon", size: 36 },
  Blocked: { color: "#f97316", shape: "octagon", size: 32 },
  Device: { color: "#2dd4bf", shape: "triangle", size: 22 },
  IP: { color: "#22d3ee", shape: "triangle", size: 20 },
  Phone: { color: "#34d399", shape: "triangle", size: 20 },
  Email: { color: "#5eead4", shape: "triangle", size: 18 },
  Address: { color: "#86efac", shape: "vee", size: 20 },
  Branch: { color: "#fbbf24", shape: "square", size: 20 },
  Case: { color: "#e879f9", shape: "star", size: 34 },
  Lesson: { color: "#4ade80", shape: "tag", size: 26 },
  Signal: { color: "#fb7185", shape: "hexagon", size: 30 },
  AgentRun: { color: "#c084fc", shape: "round-hexagon", size: 26 },
  Finding: { color: "#fda4af", shape: "round-tag", size: 22 },
  SAR: { color: "#fb923c", shape: "rectangle", size: 26 },
  Alert: { color: "#f87171", shape: "round-triangle", size: 22 },
  Playbook: { color: "#a3e635", shape: "barrel", size: 26 },
};

function edgeLabel(e: GEdge): string {
  if (e.rel === "TRANSFER" || e.rel === "CASH_DEPOSIT") return money(e.amount as number);
  if (e.rel === "OWNS" && e.pct != null) return `${e.pct}%`;
  if (e.rel === "MATCHES_CONSORTIUM") return "consortium";
  return "";
}

export function toElements(g: Subgraph): ElementDefinition[] {
  const ids = new Set(g.nodes.map((n) => n.id));
  const nodes: ElementDefinition[] = g.nodes.map((n: GNode) => ({
    data: {
      id: n.id, label: (n.label || n.id).slice(0, 34), kind: n.kind,
      color: KIND_STYLE[n.kind]?.color ?? "#cbd5e1", shape: KIND_STYLE[n.kind]?.shape ?? "ellipse",
      size: KIND_STYLE[n.kind]?.size ?? 24, country: n.country ?? "",
    },
    classes: [n.focus ? "focus" : "", n.alert ? "alerted" : ""].join(" "),
  }));
  const edges: ElementDefinition[] = g.edges
    .filter((e) => ids.has(e.source) && ids.has(e.target))
    .map((e) => ({
      data: { id: e.id, source: e.source, target: e.target, rel: e.rel, label: edgeLabel(e) },
      classes: ["TRANSFER", "CASH_DEPOSIT"].includes(e.rel) ? "money" : e.rel === "OWNS" ? "own" : "link",
    }));
  return [...nodes, ...edges];
}

export function mergeGraphs(a: Subgraph, b: Subgraph): Subgraph {
  const nodes = new Map(a.nodes.map((n) => [n.id, n]));
  for (const n of b.nodes) nodes.set(n.id, { ...nodes.get(n.id), ...n, focus: nodes.get(n.id)?.focus || n.focus });
  const edges = new Map(a.edges.map((e) => [e.id, e]));
  for (const e of b.edges) edges.set(e.id, e);
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

interface Props {
  graph: Subgraph;
  highlight?: string[];
  onSelect?: (id: string, kind: string) => void;
  layoutKey?: string;
}

export function GraphCanvas({ graph, highlight, onSelect, layoutKey }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    cy.current = cytoscape({
      container: ref.current,
      wheelSensitivity: 0.25,
      minZoom: 0.15,
      maxZoom: 3,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)", shape: "data(shape)" as any, width: "data(size)", height: "data(size)",
            label: "data(label)", color: "#cbd5e1", "font-size": 9, "font-family": "Inter, sans-serif",
            "text-valign": "bottom", "text-margin-y": 4, "text-wrap": "ellipsis", "text-max-width": "120px",
            "border-width": 1.5, "border-color": "#0b0f17", "text-outline-color": "#0b0f17", "text-outline-width": 2,
          },
        },
        { selector: "node.focus", style: { "border-width": 4, "border-color": "#ff8a1f", "font-weight": 700, color: "#fff" } },
        { selector: "node.alerted", style: { "border-width": 3, "border-color": "#ef4444" } },
        {
          selector: "edge",
          style: {
            width: 1.4, "line-color": "#334155", "target-arrow-color": "#334155", "target-arrow-shape": "triangle",
            "curve-style": "bezier", "arrow-scale": 0.8, label: "data(label)", "font-size": 8, color: "#94a3b8",
            "text-background-color": "#0b0f17", "text-background-opacity": 0.85, "text-background-padding": "2px",
            "font-family": "JetBrains Mono, monospace",
          },
        },
        { selector: "edge.money", style: { "line-color": "#64748b", "target-arrow-color": "#64748b", width: 2 } },
        { selector: "edge.own", style: { "line-color": "#a78bfa", "target-arrow-color": "#a78bfa", "line-style": "solid", width: 2 } },
        { selector: "edge.link", style: { "line-style": "dashed", "target-arrow-shape": "none", "line-color": "#2dd4bf88" } },
        { selector: ".dim", style: { opacity: 0.12 } },
        { selector: "node.hl", style: { "border-width": 4, "border-color": "#fde047", color: "#fff" } },
        { selector: "edge.hl", style: { "line-color": "#fde047", "target-arrow-color": "#fde047", width: 3.5, color: "#fde047" } },
      ],
    });
    cy.current.on("tap", "node", (evt) => onSelect?.(evt.target.id(), evt.target.data("kind")));
    return () => cy.current?.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    const els = toElements(graph);
    const wanted = new Set(els.map((e) => e.data.id as string));
    c.batch(() => {
      c.elements().forEach((el) => { if (!wanted.has(el.id())) el.remove(); });
      for (const el of els) {
        const existing = c.getElementById(el.data.id as string);
        if (existing.nonempty()) {
          existing.data(el.data);
          if (el.classes) existing.classes(el.classes as string);
        } else {
          c.add(el);
        }
      }
    });
    if (c.nodes().length) {
      c.layout({
        name: "fcose", animate: c.nodes().length < 160, animationDuration: 450, randomize: false, nodeRepulsion: 9000,
        idealEdgeLength: 90, packComponents: true, fit: true, padding: 30,
      } as any).run();
    }
  }, [graph, layoutKey]);

  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    c.elements().removeClass("dim hl");
    if (highlight && highlight.length) {
      const set = new Set(highlight);
      const nodes = c.nodes().filter((n) => set.has(n.id()));
      const edges = nodes.edgesWith(nodes);
      c.elements().not(nodes.union(edges)).addClass("dim");
      nodes.addClass("hl");
      edges.addClass("hl");
      if (nodes.length) c.animate({ fit: { eles: nodes, padding: 60 }, duration: 350 });
    }
  }, [highlight]);

  return <div className="graph-canvas" ref={ref} />;
}

export function Legend({ kinds }: { kinds: string[] }) {
  return (
    <div className="legend">
      {kinds.map((k) => (
        <span key={k} className="legend-item">
          <i style={{ background: KIND_STYLE[k]?.color ?? "#cbd5e1" }} /> {k}
        </span>
      ))}
    </div>
  );
}
