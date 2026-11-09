#!/usr/bin/env python3
"""
Natural-language retrieval layer: "AI retrieves, never calculates".

A planner turns the question into a small retrieval plan:

    {"metric": "<id from the catalog>", "filters": {...}, "by": "<dim or null>"}

The plan is validated against the KPI registry, then the registry runs the
SQL. The planner never produces a number. That boundary keeps every answer
reproducible, auditable and equal to what the dashboards show.

Planners (choose with --planner or RFL_PLANNER):
  stub    deterministic keyword rules. Default. Offline, no credentials.
  vertex  Gemini on Vertex AI picks the plan from the catalog.
          Needs requirements-llm.txt, GOOGLE_CLOUD_PROJECT and ADC.

Exit codes: 0 answered, 2 no valid plan (or planner not configured),
3 the model said no metric answers the question.

CLI:
    python ai_query/ask.py --catalog
    python ai_query/ask.py "show burdened cost per sale by channel"
    python ai_query/ask.py --planner vertex "which store had the highest average ticket?"
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_query.planner import (  # noqa: E402
    LLMPlanner, PlanError, StubPlanner, UnanswerableQuestion, build_catalog, require_valid,
)
from ai_query.vertex import ProviderConfigError  # noqa: E402  (no SDK import at load time)
from registry import query  # noqa: E402

PLANNERS = ("stub", "vertex")


def make_planner(name: str, registry: dict):
    if name == "stub":
        return StubPlanner()
    if name == "vertex":
        from ai_query.vertex import VertexGeminiClient
        return LLMPlanner(VertexGeminiClient(), registry)
    raise ValueError(f"unknown planner '{name}'; choose one of: {', '.join(PLANNERS)}")


def answer(question: str, planner, registry: dict) -> dict:
    """Plan, validate, execute. Raises PlanError or UnanswerableQuestion."""
    plan = require_valid(planner.plan(question), registry)
    sql, cols, rows = query.run_metric(plan["metric"], plan["filters"], plan["by"])
    return {"question": question, "planner": planner.name, "plan": plan,
            "sql": sql, "columns": cols, "rows": rows}


def print_answer(res: dict, registry: dict) -> None:
    plan, rows = res["plan"], res["rows"]
    m = registry["metrics"][plan["metric"]]
    print(f'Q: {res["question"]}')
    print(f'Retrieval plan (chosen by planner "{res["planner"]}", NOT computed by it):')
    print(f'   metric  = {plan["metric"]}  ("{m["label"]}")')
    print(f'   filters = {plan["filters"] or "{}"}')
    print(f'   by      = {plan["by"]}')
    print('Computed in SQL by the registry over gold.*:')
    if plan["by"]:
        width = max((len(str(r[0])) for r in rows), default=8)
        for r in rows:
            v = f"{r[1]:,.2f}" if isinstance(r[1], float) else str(r[1])
            print(f'   {str(r[0]):<{width}}  {v:>14}')
    else:
        v = rows[0][0] if rows else None
        v = f"{v:,.2f}" if isinstance(v, float) else str(v)
        print(f'   {m["label"]} = {v}  [{m["unit"]}]')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ask the lakehouse a question in plain English.")
    ap.add_argument("question", nargs="?", help="a natural-language question")
    ap.add_argument("--catalog", action="store_true", help="print the catalog a model is given")
    ap.add_argument("--planner", choices=PLANNERS, default=os.environ.get("RFL_PLANNER", "stub"),
                    help="who picks the plan (default: $RFL_PLANNER, else stub)")
    ap.add_argument("--json", action="store_true", help="emit the plan and result as JSON")
    args = ap.parse_args(argv)

    registry = query.load_registry()

    if args.catalog or not args.question:
        print(json.dumps(build_catalog(registry), indent=2))
        return 0

    # Any other error (auth, network, quota) propagates with its traceback.
    # There is no silent fallback to the stub.
    try:
        planner = make_planner(args.planner, registry)
        res = answer(args.question, planner, registry)
    except ProviderConfigError as e:
        print(f"Planner '{args.planner}' is not configured: {e}", file=sys.stderr)
        return 2
    except UnanswerableQuestion as e:
        print(f"Not answerable from the KPI registry: {e}", file=sys.stderr)
        return 3
    except PlanError as e:
        print(f"No valid retrieval plan: {e}", file=sys.stderr)
        return 2

    if args.json:
        out = {"question": res["question"], "planner": res["planner"], "plan": res["plan"],
               "result": [dict(zip(res["columns"], r)) for r in res["rows"]]}
        print(json.dumps(out, default=str, indent=2))
    else:
        print_answer(res, registry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
