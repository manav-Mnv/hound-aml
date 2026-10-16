"""hound CLI: seed the graphs, run monitoring, investigate, evaluate, serve."""
from __future__ import annotations

import argparse
import json
import sys


def _print_event(e: dict) -> None:
    t = e.get("type")
    agent = e.get("agent", "")
    if t == "tool_call":
        print(f"  -> {e['tool']}({json.dumps(e['args'])[:140]})")
    elif t == "evidence":
        print(f"     [{e['evidence_id']}] {e['summary'][:220]}")
    elif t in ("thinking", "message", "warning", "info", "merged"):
        print(f"  {agent} {t}: {e.get('text', '')[:400]}")
    elif t == "action":
        print(f"  ** {e['tool']}: {json.dumps(e['result'])[:220]}")
    elif t == "handoff":
        print(f"  == handoff {e['from']} -> {e['to']}")
    elif t == "review":
        r = e["review"]
        print(f"  reviewer: {r['grounded']}/{r['sentences']} sentences grounded, {len(r['issues'])} issue(s)")
    elif t == "case_opened":
        print(f"case {e['case_id']} opened")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="hound")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="generate synthetic banks, load FalkorDB, run analytics, rules and triage")
    inv = sub.add_parser("investigate", help="investigate one alert (or the top-scored one)")
    inv.add_argument("alert", nargs="?")
    inv.add_argument("--tenant", default="alpha")
    inv.add_argument("--mode", default="auto", choices=["auto", "offline"])
    ev = sub.add_parser("eval", help="benchmark rules-only vs Hound against ground truth")
    ev.add_argument("--tenant", default="alpha")
    ev.add_argument("--mode", default="offline", choices=["auto", "offline"])
    ev.add_argument("--limit", type=int)
    srv = sub.add_parser("serve", help="run the API and web UI")
    srv.add_argument("--host", default="0.0.0.0")
    srv.add_argument("--port", type=int, default=8000)
    sub.add_parser("mcp", help="run the MCP server over stdio")
    args = ap.parse_args(argv)

    if args.cmd == "seed":
        from . import analytics, rules, triage
        from .world.loader import seed
        seed()
        for t in ("alpha", "beta"):
            print(analytics.run_analytics(t))
            print(rules.run_rules(t))
            triage.score_alerts(t)
        print("ready")
    elif args.cmd == "investigate":
        from . import orchestrator, triage
        alert = args.alert or next(a["id"] for a in triage.queue(args.tenant) if not a.get("case_id"))
        out = orchestrator.investigate(args.tenant, alert, _print_event, mode=args.mode)
        print(json.dumps(out, indent=2, default=str))
    elif args.cmd == "eval":
        from . import evaluate
        print(json.dumps(evaluate.run(args.tenant, args.mode, args.limit), indent=2))
    elif args.cmd == "serve":
        import uvicorn
        uvicorn.run("hound.api:app", host=args.host, port=args.port)
    elif args.cmd == "mcp":
        from .mcp_server import main as mcp_main
        mcp_main()


if __name__ == "__main__":
    main(sys.argv[1:])
