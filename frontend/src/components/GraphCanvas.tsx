import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { type Core, type ElementDefinition, type EventObject } from "cytoscape";
import fcose from "cytoscape-fcose";
import type { GNode, Subgraph } from "../types";
import { money } from "../api";
import { RULE_SHORT, humanize, kindLabel, nodeCaption } from "../format";

cytoscape.use(fcose);

// Lucide-style 24px stroke icons drawn inside each node.
const ICON = {
  person: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>',
  company: '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4M8 6h.01M12 6h.01M16 6h.01M8 10h.01M12 10h.01M16 10h.01M8 14h.01M12 14h.01M16 14h.01"/>',
  account: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20M6 15h4"/>',
  globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20"/>',
  ban: '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M12 8v4M12 16h.01"/>',
  laptop: '<rect x="4" y="4" width="16" height="11" rx="1.5"/><path d="M2 19h20"/>',
  wifi: '<path d="M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M12 20h.01"/>',
  phone: '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',
  mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/>',
  pin: '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>',
  bank: '<path d="M3 22h18M6 18v-7M10 18v-7M14 18v-7M18 18v-7M12 2l9 5H3z"/>',
  case: '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
  bulb: '<path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/>',
  signal: '<circle cx="12" cy="12" r="2"/><path d="M16.2 7.8a6 6 0 0 1 0 8.5M7.8 16.2a6 6 0 0 1 0-8.5M19.1 4.9a10 10 0 0 1 0 14.2M4.9 19.1a10 10 0 0 1 0-14.2"/>',
  bot: '<rect x="4" y="8" width="16" height="12" rx="2"/><path d="M12 8V4M9 4h6M9 13v2M15 13v2"/>',
  flag: '<path d="M4 22V4a1 1 0 0 1 1-1h12l-2 5 2 5H5"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8"/>',
  alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  book: '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2zM22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
  dot: '<circle cx="12" cy="12" r="4"/>',
};

type KindStyle = { color: string; shape: string; size: number; icon: string };
export const KIND_STYLE: Record<string, KindStyle> = {
  Person: { color: "#60a5fa", shape: "ellipse", size: 34, icon: ICON.person },
  Company: { color: "#a78bfa", shape: "round-rectangle", size: 36, icon: ICON.company },
  Account: { color: "#cbd5e1", shape: "round-rectangle", size: 32, icon: ICON.account },
  External: { color: "#f59e0b", shape: "round-rectangle", size: 32, icon: ICON.globe },
  Sanctioned: { color: "#ef4444", shape: "octagon", size: 40, icon: ICON.ban },
  Blocked: { color: "#f97316", shape: "octagon", size: 36, icon: ICON.shield },
  Device: { color: "#2dd4bf", shape: "ellipse", size: 26, icon: ICON.laptop },
  IP: { color: "#22d3ee", shape: "ellipse", size: 26, icon: ICON.wifi },
  Phone: { color: "#34d399", shape: "ellipse", size: 26, icon: ICON.phone },
  Email: { color: "#5eead4", shape: "ellipse", size: 26, icon: ICON.mail },
  Address: { color: "#86efac", shape: "ellipse", size: 26, icon: ICON.pin },
  Branch: { color: "#fbbf24", shape: "ellipse", size: 28, icon: ICON.bank },
  Case: { color: "#e879f9", shape: "round-rectangle", size: 40, icon: ICON.case },
  Lesson: { color: "#4ade80", shape: "ellipse", size: 30, icon: ICON.bulb },
  Signal: { color: "#fb7185", shape: "ellipse", size: 32, icon: ICON.signal },
  AgentRun: { color: "#c084fc", shape: "ellipse", size: 30, icon: ICON.bot },
  Finding: { color: "#fda4af", shape: "ellipse", size: 28, icon: ICON.flag },
  SAR: { color: "#fb923c", shape: "round-rectangle", size: 32, icon: ICON.file },
  Alert: { color: "#f87171", shape: "ellipse", size: 30, icon: ICON.alert },
  Playbook: { color: "#a3e635", shape: "round-rectangle", size: 32, icon: ICON.book },
};
const FALLBACK: KindStyle = { color: "#94a3b8", shape: "ellipse", size: 26, icon: ICON.dot };
export const kindStyle = (k: string) => KIND_STYLE[k] ?? FALLBACK;

const iconCache = new Map<string, string>();
export function iconUri(kind: string): string {
  let uri = iconCache.get(kind);
  if (!uri) {
    const s = kindStyle(kind);
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="${s.color}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${s.icon}</svg>`;
    uri = `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
    iconCache.set(kind, uri);
  }
  return uri;
}

const MONEY = new Set(["TRANSFER", "CASH_DEPOSIT"]);

interface AggEdge { id: string; source: string; target: string; rel: string; amount: number; count: number; pct?: number }

/** Graph -> Cytoscape elements. Parallel transfers between the same two accounts collapse into one edge. */
export function toElements(g: Subgraph): ElementDefinition[] {
  const ids = new Set(g.nodes.map((n) => n.id));
  const agg = new Map<string, AggEdge>();
  for (const e of g.edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue;
    const id = `${e.source}|${e.rel}|${e.target}`;
    const cur = agg.get(id);
    if (cur) { cur.amount += Number(e.amount ?? 0); cur.count += 1; }
    else agg.set(id, { id, source: e.source, target: e.target, rel: e.rel, amount: Number(e.amount ?? 0), count: 1, pct: e.pct as number | undefined });
  }
  const maxAmt = Math.max(1, ...[...agg.values()].filter((e) => MONEY.has(e.rel)).map((e) => e.amount));

  const nodes: ElementDefinition[] = g.nodes.map((n: GNode) => {
    const s = kindStyle(n.kind);
    const { title, sub } = nodeCaption(n);
    return {
      data: {
        id: n.id, kind: n.kind, label: sub ? `${title}\n${sub}` : title, color: s.color, shape: s.shape,
        size: n.focus ? Math.round(s.size * 1.3) : s.size, icon: iconUri(n.kind), raw: n,
      },
      classes: [n.focus ? "focus" : "", n.alert ? "alerted" : ""].join(" ").trim(),
    };
  });
  const edges: ElementDefinition[] = [...agg.values()].map((e) => {
    const isMoney = MONEY.has(e.rel);
    const label = isMoney ? `${money(e.amount)}${e.count > 1 ? ` ×${e.count}` : ""}`
      : e.rel === "OWNS" && e.pct != null ? `${e.pct}%` : e.rel === "MATCHES_CONSORTIUM" ? "consortium" : "";
    return {
      data: {
        id: e.id, source: e.source, target: e.target, rel: e.rel, label, amount: e.amount, count: e.count,
        width: isMoney ? +(1.3 + 3.7 * Math.sqrt(e.amount / maxAmt)).toFixed(2) : 1.3,
      },
      classes: isMoney ? "money" : e.rel === "OWNS" || e.rel === "DIRECTOR_OF" ? "own" : "link",
    };
  });
  return [...nodes, ...edges];
}

export function mergeGraphs(a: Subgraph, b: Subgraph): Subgraph {
  const nodes = new Map(a.nodes.map((n) => [n.id, n]));
  for (const n of b.nodes) {
    const prev = nodes.get(n.id);
    const merged = { ...prev, ...n, focus: prev?.focus || n.focus, alert: prev?.alert || n.alert };
    // Keep a human label (holder name) over a later bare id for the same node.
    if (prev?.label && prev.label !== prev.id && (!n.label || n.label === n.id)) merged.label = prev.label;
    nodes.set(n.id, merged);
  }
  const edges = new Map(a.edges.map((e) => [e.id, e]));
  for (const e of b.edges) edges.set(e.id, e);
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

const STYLE: any[] = [
  {
    selector: "node",
    style: {
      shape: "data(shape)", width: "data(size)", height: "data(size)",
      "background-color": "#0f1521", "border-width": 2, "border-color": "data(color)",
      "background-image": "data(icon)", "background-fit": "none", "background-width": "54%", "background-height": "54%",
      "background-clip": "none", "background-image-containment": "over",
      label: "data(label)", color: "#dbe3ee", "font-size": 10, "font-weight": 500, "font-family": "Inter, system-ui, sans-serif",
      "text-valign": "bottom", "text-halign": "center", "text-margin-y": 6, "text-wrap": "wrap", "text-max-width": "140px",
      "line-height": 1.35, "text-background-color": "#090c12", "text-background-opacity": 0.78,
      "text-background-shape": "round-rectangle", "text-background-padding": "3px", "min-zoomed-font-size": 5,
      "transition-property": "opacity, border-color, border-width, underlay-opacity", "transition-duration": 0.18,
    },
  },
  {
    selector: "node.alerted",
    style: { "border-color": "#f05252", "border-width": 2.5, "underlay-color": "#f05252", "underlay-opacity": 0.2, "underlay-padding": 7, "underlay-shape": "ellipse" },
  },
  {
    selector: "node.focus",
    style: {
      "border-color": "#ff8a1f", "border-width": 3, "underlay-color": "#ff8a1f", "underlay-opacity": 0.28, "underlay-padding": 10,
      "underlay-shape": "ellipse", "background-color": "#1a1410", color: "#ffffff", "font-weight": 700, "font-size": 11,
    },
  },
  { selector: "node:selected", style: { "border-color": "#fde047", "border-width": 3 } },
  { selector: "node.hl", style: { "border-color": "#fde047", "border-width": 3, "underlay-color": "#fde047", "underlay-opacity": 0.12, "underlay-padding": 6, "underlay-shape": "ellipse", color: "#fff" } },
  {
    selector: "edge",
    style: {
      width: "data(width)", "curve-style": "bezier", "control-point-step-size": 26, "line-color": "#3a475b",
      "target-arrow-color": "#3a475b", "target-arrow-shape": "triangle", "arrow-scale": 0.8, opacity: 0.9,
      label: "data(label)", "font-size": 8.5, "font-family": "JetBrains Mono, ui-monospace, monospace", color: "#aab6c7",
      "text-rotation": "autorotate", "text-background-color": "#090c12", "text-background-opacity": 0.92,
      "text-background-shape": "round-rectangle", "text-background-padding": "2px", "min-zoomed-font-size": 7,
      "transition-property": "opacity, line-color", "transition-duration": 0.18,
    },
  },
  {
    selector: "edge.money",
    style: {
      "line-fill": "linear-gradient", "line-gradient-stop-colors": "#263142 #8796ab", "line-gradient-stop-positions": "0 100",
      "target-arrow-color": "#9aa8bb",
    },
  },
  { selector: "edge.own", style: { "line-color": "#8b74d6", "target-arrow-color": "#a78bfa", width: 1.8, color: "#c9b8ff" } },
  {
    selector: "edge.link",
    style: { "line-style": "dashed", "line-dash-pattern": [5, 4], "target-arrow-shape": "none", "line-color": "rgba(45,212,191,0.45)" },
  },
  { selector: ".dim", style: { opacity: 0.08 } },
  { selector: ".faded", style: { opacity: 0.16 } },
  { selector: ".hidden-kind", style: { display: "none" } },
  {
    selector: "edge.hl",
    style: { "line-fill": "solid", "line-color": "#fde047", "target-arrow-color": "#fde047", color: "#fde047", opacity: 1 },
  },
  { selector: "edge.hover", style: { "line-fill": "solid", "line-color": "#e2e8f0", "target-arrow-color": "#e2e8f0", color: "#fff", opacity: 1 } },
];

interface Props {
  graph: Subgraph;
  highlight?: string[];
  onSelect?: (id: string, kind: string) => void;
  layoutKey?: string;
  legend?: boolean;
}

type Tip =
  | { type: "node"; x: number; y: number; r: number; node: GNode }
  | { type: "edge"; x: number; y: number; r: number; rel: string; amount: number; count: number; label: string };

const FIT_ZOOM = 1.5;

export function GraphCanvas({ graph, highlight, onSelect, layoutKey, legend = true }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const layoutRef = useRef<cytoscape.Layouts | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  const runLayout = (randomize: boolean) => {
    const c = cy.current;
    if (!c || !c.nodes().length) return;
    // Evidence can stream in faster than a layout animates: finish the old one before starting the next.
    layoutRef.current?.stop();
    c.stop(true, true);
    c.resize();
    c.maxZoom(FIT_ZOOM); // keep small graphs from filling the screen with three nodes
    const layout = c.layout({
      name: "fcose", quality: "default", animate: c.nodes().length < 220, animationDuration: 500, randomize,
      nodeDimensionsIncludeLabels: true, nodeSeparation: 80, nodeRepulsion: () => 11000,
      idealEdgeLength: (e: any) => (e.hasClass("link") ? 60 : 100), edgeElasticity: () => 0.4, gravity: 0.3,
      numIter: 2500, packComponents: true, fit: true, padding: 48,
    } as any);
    layout.one("layoutstop", () => c.maxZoom(3));
    layoutRef.current = layout;
    layout.run();
  };

  useEffect(() => {
    if (!ref.current) return;
    const c = cytoscape({ container: ref.current, wheelSensitivity: 0.25, minZoom: 0.1, maxZoom: 3, style: STYLE, boxSelectionEnabled: false });
    cy.current = c;
    c.on("tap", "node", (evt) => onSelect?.(evt.target.id(), evt.target.data("kind")));
    c.on("mouseover", "node", (evt: EventObject) => {
      const n = evt.target;
      if (!c.elements(".hl").length) c.elements().not(n.closedNeighborhood()).addClass("faded");
      const p = n.renderedPosition();
      setTip({ type: "node", x: p.x, y: p.y, r: n.renderedOuterHeight() / 2, node: n.data("raw") });
      if (ref.current) ref.current.style.cursor = "pointer";
    });
    c.on("mouseover", "edge", (evt: EventObject) => {
      const e = evt.target;
      e.addClass("hover");
      const p = e.renderedMidpoint();
      setTip({ type: "edge", x: p.x, y: p.y, r: 4, rel: e.data("rel"), amount: e.data("amount"), count: e.data("count"), label: e.data("label") });
    });
    c.on("mouseout", "node, edge", () => {
      c.elements().removeClass("faded hover");
      setTip(null);
      if (ref.current) ref.current.style.cursor = "";
    });
    c.on("viewport", () => setTip(null));
    // The header above the canvas changes height with the selection; keep Cytoscape's cached size honest.
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); c.destroy(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    const els = toElements(graph);
    const wanted = new Set(els.map((e) => e.data.id as string));
    let added = 0;
    c.batch(() => {
      c.elements().forEach((el) => { if (!wanted.has(el.id())) el.remove(); });
      for (const el of els) {
        const existing = c.getElementById(el.data.id as string);
        if (existing.nonempty()) {
          existing.data(el.data);
          existing.classes((el.classes as string) || "");
        } else {
          c.add(el);
          added += 1;
        }
      }
    });
    applyHidden(c, hidden);
    runLayout(added > c.nodes().length / 2);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, layoutKey]);

  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    c.elements().removeClass("dim hl");
    if (highlight && highlight.length) {
      const set = new Set(highlight);
      const picked = c.nodes().filter((n) => set.has(n.id()));
      // A single clicked node: show it with its direct connections.
      const nodes = highlight.length === 1 ? picked.closedNeighborhood().nodes() : picked;
      const edges = nodes.edgesWith(nodes);
      c.elements().not(nodes.union(edges)).addClass("dim");
      nodes.addClass("hl");
      edges.addClass("hl");
      if (highlight.length === 1) c.nodes().filter((n) => !set.has(n.id())).removeClass("hl");
      if (nodes.length) {
        c.maxZoom(1.8);
        c.animate({ fit: { eles: nodes, padding: 70 }, duration: 380, easing: "ease-in-out-cubic", complete: () => c.maxZoom(3) } as any);
      }
    }
  }, [highlight]);

  useEffect(() => { if (cy.current) applyHidden(cy.current, hidden); }, [hidden]);

  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const n of graph.nodes) m.set(n.kind, (m.get(n.kind) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [graph]);

  const zoomBy = (f: number) => {
    const c = cy.current;
    if (!c) return;
    c.animate({ zoom: { level: c.zoom() * f, renderedPosition: { x: c.width() / 2, y: c.height() / 2 } }, duration: 180 } as any);
  };
  const fit = () => {
    const c = cy.current;
    if (!c) return;
    c.maxZoom(FIT_ZOOM);
    c.animate({ fit: { eles: c.elements(":visible"), padding: 48 }, duration: 300, complete: () => c.maxZoom(3) } as any);
  };
  const toggleKind = (k: string) => setHidden((h) => {
    const n = new Set(h);
    if (n.has(k)) n.delete(k); else n.add(k);
    return n;
  });

  return (
    <>
      <div className="graph-canvas" ref={ref} />
      {tip && <GraphTip tip={tip} />}
      <div className="g-controls">
        <button onClick={() => zoomBy(1.3)} title="Zoom in" aria-label="Zoom in">+</button>
        <button onClick={() => zoomBy(1 / 1.3)} title="Zoom out" aria-label="Zoom out">−</button>
        <button onClick={fit} title="Fit graph to view" aria-label="Fit graph">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></svg>
        </button>
        <button onClick={() => runLayout(true)} title="Re-run layout" aria-label="Re-run layout">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5" /></svg>
        </button>
      </div>
      {legend && counts.length > 0 && (
        <div className="legend">
          {counts.map(([k, n]) => (
            <button key={k} className={`legend-item ${hidden.has(k) ? "off" : ""}`} onClick={() => toggleKind(k)}
              title={hidden.has(k) ? `Show ${kindLabel(k)} nodes` : `Hide ${kindLabel(k)} nodes`}>
              <KindIcon kind={k} /> {kindLabel(k)} <span className="legend-n">{n}</span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}

function applyHidden(c: Core, hidden: Set<string>) {
  c.batch(() => {
    c.nodes().forEach((n) => { if (hidden.has(n.data("kind"))) n.addClass("hidden-kind"); else n.removeClass("hidden-kind"); });
  });
}

export function KindIcon({ kind, size = 16 }: { kind: string; size?: number }) {
  const s = kindStyle(kind);
  return (
    <span className={`kind-icon ${s.shape.includes("rect") ? "sq" : ""}`} style={{ width: size, height: size, borderColor: s.color }}>
      <img src={iconUri(kind)} alt="" />
    </span>
  );
}

function GraphTip({ tip }: { tip: Tip }) {
  const below = tip.y < 150;
  const style = { left: tip.x, top: below ? tip.y + tip.r + 12 : tip.y - tip.r - 12 };
  if (tip.type === "edge") {
    const isMoney = MONEY.has(tip.rel);
    return (
      <div className={`g-tip ${below ? "below" : ""}`} style={style}>
        <div className="g-tip-kind">{humanize(tip.rel)}</div>
        {isMoney ? (
          <div className="g-tip-title">{money(tip.amount)} <span className="muted">in {tip.count} {tip.count === 1 ? "transfer" : "transfers"}</span></div>
        ) : tip.label ? <div className="g-tip-title">{tip.label}</div> : null}
      </div>
    );
  }
  const n = tip.node;
  const { title } = nodeCaption(n);
  const rows: [string, string][] = [];
  rows.push(["ID", n.id]);
  if (n.holder && n.holder !== title) rows.push(["Holder", String(n.holder)]);
  if (n.acct_type) rows.push(["Type", String(n.acct_type)]);
  if (n.bank) rows.push(["Bank", String(n.bank)]);
  if (n.rule_name) rows.push(["Rule", `${n.rule} · ${n.rule_name}`]);
  else if (n.kind === "Alert") rows.push(["Rule", RULE_SHORT[n.id.split("-")[1]] ?? ""]);
  if (n.disposition) rows.push(["Outcome", humanize(String(n.disposition))]);
  if (n.country) rows.push(["Country", String(n.country)]);
  if (typeof n.alerts === "number" && n.alerts > 0) rows.push(["Alerts", String(n.alerts)]);
  const text = typeof n.text === "string" && n.text.length > title.length ? n.text : "";
  return (
    <div className={`g-tip ${below ? "below" : ""}`} style={style}>
      <div className="g-tip-kind"><KindIcon kind={n.kind} size={14} /> {kindLabel(n.kind)}
        {n.focus && <span className="g-tip-tag">subject</span>}{n.alert && <span className="g-tip-tag red">alerted</span>}
      </div>
      <div className="g-tip-title">{title}</div>
      {text && <div className="g-tip-text">{text.length > 180 ? `${text.slice(0, 179)}…` : text}</div>}
      <dl>{rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd className={k === "ID" ? "mono" : ""}>{v}</dd></div>)}</dl>
    </div>
  );
}
