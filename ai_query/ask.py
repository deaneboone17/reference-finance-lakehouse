#!/usr/bin/env python3
"""
Natural-language retrieval layer -- "AI retrieves, never calculates".

The design rule this demonstrates: a language model is allowed to decide WHICH
registry metric answers a question and WHICH filters to apply. It is never
allowed to produce the number itself. The number is always computed in SQL by
the KPI registry against the governed gold tables. So the model's entire job
is to emit a small, validated retrieval plan:

    {"metric": "<id from the catalog>", "filters": {...}, "by": "<dim or null>"}

and the registry executes it. That boundary means answers are always
reproducible, auditable, and consistent with every dashboard -- the model
cannot hallucinate a KPI or do its own arithmetic.

In this reference repo the "model" is a deterministic keyword stub
(plan_from_question) so the project runs offline with no API key. The
docstring on that function shows exactly where a real LLM call would slot in;
its contract is identical -- it returns the same plan dict, constrained to the
metric catalog printed by --catalog.

CLI:
    python ai_query/ask.py --catalog
    python ai_query/ask.py "what was total revenue last year"
    python ai_query/ask.py "show burdened cost per sale by channel"
    python ai_query/ask.py "revenue from paid search"
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from registry import query  # noqa: E402

CHANNELS = ["paid_search", "paid_social", "email", "organic_search", "referral", "walk_in"]
CHANNEL_WORDS = {
    "paid search": "paid_search", "ppc": "paid_search", "google": "paid_search",
    "paid social": "paid_social", "social": "paid_social", "meta": "paid_social",
    "email": "email", "newsletter": "email",
    "organic": "organic_search", "seo": "organic_search",
    "referral": "referral", "word of mouth": "referral",
    "walk in": "walk_in", "walk-in": "walk_in", "walkin": "walk_in",
}
STORE_WORDS = {
    "riverside": "Riverside", "highland": "Highland Park",
    "oakmont": "Oakmont", "lakeside": "Lakeside",
}

# Ordered keyword -> metric rules. First match wins. More specific phrases are
# listed before the generic ones so "cost per sale" is not mistaken for "sales".
METRIC_RULES = [
    (("burdened", "fully loaded", "loaded cost", "true cost"), "burdened_cost_per_sale"),
    (("media cost", "cost per sale", "cac", "acquisition cost"), "media_cost_per_sale"),
    (("lead to sale", "conversion", "close rate", "win rate", "lead-to-sale"), "lead_to_sale_rate"),
    (("average ticket", "avg ticket", "average order", "ticket size"), "average_ticket"),
    (("gross margin", "margin"), "gross_margin"),
    (("how many", "count", "number of sales", "transactions", "sales volume"), "sales_count"),
    (("revenue", "sales", "top line", "turnover"), "total_revenue"),
]


def plan_from_question(question: str) -> dict:
    """
    Turn a natural-language question into a validated retrieval plan.

    >>> REPLACE-ME-WITH-AN-LLM <<<
    In production this is a single constrained LLM call: give the model the
    registry catalog (query.load_registry) and the question, and have it
    return JSON {"metric", "filters", "by"} -- nothing else. The model selects;
    it does not compute. The deterministic keyword matcher below stands in for
    that call so the repo runs with no credentials.
    """
    q = question.lower()

    metric = None
    for keywords, mid in METRIC_RULES:
        if any(k in q for k in keywords):
            metric = mid
            break
    if metric is None:
        metric = "total_revenue"  # safe default

    filters: dict[str, str] = {}
    for word, canonical in CHANNEL_WORDS.items():
        if word in q:
            filters["channel"] = canonical
            break
    for word, canonical in STORE_WORDS.items():
        if word in q:
            filters["store"] = canonical
            break

    # year / month mentions -> month filter when a full YYYY-MM is implied.
    import re
    m = re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])\b", q)
    if m:
        filters["month"] = m.group(0)

    by = None
    if "by channel" in q or "per channel" in q or "each channel" in q:
        by = "channel"
    elif "by store" in q or "per store" in q or "each store" in q or "by location" in q:
        by = "store"
    elif "by month" in q or "monthly" in q or "over time" in q or "by month" in q:
        by = "month"

    # metrics sourced from the per-channel mart only support a channel breakdown
    mart_only = {"media_cost_per_sale", "burdened_cost_per_sale", "lead_to_sale_rate"}
    if metric in mart_only:
        filters.pop("store", None)
        filters.pop("month", None)
        if by in ("store", "month"):
            by = "channel"

    return {"metric": metric, "filters": filters, "by": by}


def main() -> int:
    ap = argparse.ArgumentParser(description="Ask the lakehouse a question in plain English.")
    ap.add_argument("question", nargs="?", help="a natural-language question")
    ap.add_argument("--catalog", action="store_true", help="print the metric catalog a real LLM would be given")
    ap.add_argument("--json", action="store_true", help="emit the plan and result as JSON")
    args = ap.parse_args()

    registry = query.load_registry()

    if args.catalog or not args.question:
        catalog = {
            mid: {
                "label": m["label"],
                "description": m["description"],
                "unit": m["unit"],
                "dimensions": list(m.get("filters", {})),
            }
            for mid, m in registry["metrics"].items()
        }
        print(json.dumps({"metrics": catalog}, indent=2))
        return 0

    plan = plan_from_question(args.question)
    sql, cols, rows = query.run_metric(plan["metric"], plan["filters"], plan["by"])

    if args.json:
        result = [dict(zip(cols, r)) for r in rows]
        print(json.dumps({"question": args.question, "plan": plan, "result": result}, default=str, indent=2))
        return 0

    m = registry["metrics"][plan["metric"]]
    print(f'Q: {args.question}')
    print(f'Retrieval plan (chosen by the model, NOT computed by it):')
    print(f'   metric  = {plan["metric"]}  ("{m["label"]}")')
    print(f'   filters = {plan["filters"] or "{}"}')
    print(f'   by      = {plan["by"]}')
    print(f'Computed in SQL by the registry over gold.*:')
    if plan["by"]:
        width = max((len(str(r[0])) for r in rows), default=8)
        for r in rows:
            v = f"{r[1]:,.2f}" if isinstance(r[1], float) else str(r[1])
            print(f'   {str(r[0]):<{width}}  {v:>14}')
    else:
        v = rows[0][0] if rows else None
        v = f"{v:,.2f}" if isinstance(v, float) else str(v)
        print(f'   {m["label"]} = {v}  [{m["unit"]}]')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
