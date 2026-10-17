import type { GNode } from "./types";

/** Short names for the six monitoring rules, so "ALR-R4-308899" can read as "R4 · Pass-through". */
export const RULE_SHORT: Record<string, string> = {
  R1: "Structuring", R2: "Fan-out", R3: "Fan-in", R4: "Pass-through", R5: "High-risk wire", R6: "New-account inflow",
};

export const KIND_LABEL: Record<string, string> = {
  AgentRun: "Agent run", IP: "IP address", SAR: "SAR", External: "External account", Sanctioned: "Sanctioned party",
  Blocked: "Blocked entity", Signal: "Consortium signal",
};
export const kindLabel = (k: string) => KIND_LABEL[k] ?? k;

const DISPOSITION_SHORT: Record<string, string> = {
  SAR_RECOMMENDED: "SAR recommended", SAR_FILED: "SAR filed", FALSE_POSITIVE: "False positive", MONITOR_EDD: "Monitor / EDD",
  PENDING_APPROVAL: "Pending approval", OPEN: "Open", CLOSED: "Closed",
};

export const humanize = (s: string) => s.toLowerCase().replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);

/** Colour family for an identifier, keyed on its prefix (AC-, ALR-, CASE-, EV-, ...). */
export function idTone(id: string): string {
  const p = id.split("-")[0];
  return ({
    AC: "acct", EX: "ext", ALR: "alert", CASE: "case", EV: "ev", P: "party", B: "party", GRP: "grp", SAR: "sar",
  } as Record<string, string>)[p] ?? "neutral";
}

/** Split "ALR-R4-308899" into prefix "ALR" and rest "R4-308899" for two-tone rendering. */
export function splitId(id: string): [string, string] {
  const i = id.indexOf("-");
  return i > 0 && i <= 5 ? [id.slice(0, i), id.slice(i + 1)] : ["", id];
}

/**
 * Two-line caption for a graph node: who or what it is (title), then the identifier (sub).
 * Accounts read as their holder's name with the account number underneath instead of a bare AC-number.
 */
export function nodeCaption(n: GNode): { title: string; sub: string } {
  const id = String(n.id);
  let label = n.label && n.label !== id ? String(n.label) : "";
  // Tools label some nodes "<id> <extra>" (cases, branches): keep the extra as the title.
  if (label.startsWith(`${id} `)) label = label.slice(id.length + 1);
  const country = typeof n.country === "string" && n.country && n.country !== "US" ? n.country : "";

  switch (n.kind) {
    case "Account":
    case "External": {
      const who = label || (n.holder as string) || "";
      const sub = [id, country].filter(Boolean).join(" · ");
      if (who) return { title: clip(who, 30), sub };
      return { title: id, sub: [n.kind === "External" ? (n.bank as string) : (n.acct_type as string), country].filter(Boolean).join(" · ") };
    }
    case "Alert": {
      const rule = (n.rule as string) ?? id.split("-")[1] ?? "";
      return { title: `${rule} · ${RULE_SHORT[rule] ?? "Alert"}`, sub: id };
    }
    case "Case": {
      const d = (n.disposition as string) || (n.status as string) || label;
      return { title: id.replace(/^CASE-/, "Case "), sub: d ? DISPOSITION_SHORT[d] ?? humanize(d) : "" };
    }
    case "Playbook":
      return { title: `${humanize(label || id)}`, sub: "playbook" };
    case "Lesson":
      return { title: `“${clip(label.replace(/\.\.\.$/, ""), 22)}”`, sub: "lesson" };
    case "Finding":
      return { title: clip((n.text as string) || label || id, 26), sub: id };
    case "AgentRun":
      return { title: humanize(label || "agent"), sub: "agent run" };
    case "Branch":
      return { title: label || id, sub: label ? id : "" };
    case "Person":
    case "Company":
    case "Sanctioned":
    case "Blocked":
      return { title: clip(label || id, 30), sub: [n.kind === "Sanctioned" ? "sanctioned" : "", country].filter(Boolean).join(" · ") };
    default:
      return { title: clip(label || id, 26), sub: "" };
  }
}
