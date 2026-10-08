#!/usr/bin/env python3
"""
KPI registry engine.

Loads metrics.yml and computes a registry-defined metric by running its SQL
against the DuckDB warehouse. The metric math lives in SQL, in the registry --
this module only compiles filters and breakdowns into the template and
executes it. Nothing here invents or adjusts a number.

CLI:
    python registry/query.py --list
    python registry/query.py total_revenue
    python registry/query.py total_revenue --by channel
    python registry/query.py burdened_cost_per_sale --by channel
    python registry/query.py total_revenue --filter channel=paid_search --filter month=2025-06
"""

import argparse
import os
import re
import sys

import duckdb
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_PATH = os.path.join(ROOT, "warehouse.duckdb")
METRICS_PATH = os.path.join(HERE, "metrics.yml")

# A conservative identifier pattern. Filter values that are not simple
# identifiers/dates are rejected rather than interpolated, which keeps this a
# safe retrieval surface even when a model is choosing the inputs.
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_\- ]+$")


def load_registry() -> dict:
    with open(METRICS_PATH) as f:
        return yaml.safe_load(f)


def _validate_value(value: str) -> str:
    if not _SAFE_VALUE.match(value):
        raise ValueError(f"unsafe filter value: {value!r}")
    return value.replace("'", "''")


def build_sql(metric_id: str, filters: dict, by: str | None, registry: dict) -> str:
    metrics = registry["metrics"]
    if metric_id not in metrics:
        raise KeyError(f"unknown metric '{metric_id}'. Run --list to see the catalog.")
    metric = metrics[metric_id]
    allowed = metric.get("filters", {})

    # WHERE from filters (only dimensions this metric declares are accepted).
    clauses = []
    for dim, val in filters.items():
        if dim not in allowed:
            raise KeyError(f"metric '{metric_id}' has no filterable dimension '{dim}'. "
                           f"Allowed: {', '.join(allowed) or '(none)'}")
        col = allowed[dim]
        clauses.append(f"{col} = '{_validate_value(str(val))}'")
    where = ("where " + " and ".join(clauses)) if clauses else ""

    # Optional breakdown.
    dims, group_by = "", ""
    if by:
        if by not in allowed:
            raise KeyError(f"metric '{metric_id}' cannot be broken down by '{by}'. "
                           f"Allowed: {', '.join(allowed) or '(none)'}")
        col = allowed[by]
        dims = f"{col} as {by},"
        group_by = f"group by {col} order by value desc"

    sql = metric["sql"]
    sql = sql.replace("{dims}", dims).replace("{where}", where).replace("{group_by}", group_by)
    return sql


def run_metric(metric_id: str, filters: dict | None = None, by: str | None = None):
    registry = load_registry()
    sql = build_sql(metric_id, filters or {}, by, registry)
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"warehouse not built yet: {DB_PATH}. Run the generator and dbt build first.")
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        cols = [d[0] for d in con.execute(sql).description]
        rows = con.execute(sql).fetchall()
    finally:
        con.close()
    return sql, cols, rows


def _print_catalog(registry: dict) -> None:
    print("KPI registry metrics:\n")
    for mid, m in registry["metrics"].items():
        dims = ", ".join(m.get("filters", {})) or "(none)"
        print(f"  {mid:<24} {m['label']}  [{m['unit']}]")
        print(f"  {'':<24} {m['description']}")
        print(f"  {'':<24} dimensions: {dims}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute a KPI-registry metric from the warehouse.")
    ap.add_argument("metric", nargs="?", help="metric id (see --list)")
    ap.add_argument("--list", action="store_true", help="list the metric catalog")
    ap.add_argument("--by", help="break the metric down by a dimension (e.g. channel, store, month)")
    ap.add_argument("--filter", action="append", default=[], metavar="dim=value",
                    help="filter on a dimension; repeatable")
    ap.add_argument("--show-sql", action="store_true", help="print the compiled SQL")
    args = ap.parse_args()

    registry = load_registry()
    if args.list or not args.metric:
        _print_catalog(registry)
        return 0

    filters = {}
    for f in args.filter:
        if "=" not in f:
            print(f"bad --filter '{f}', expected dim=value", file=sys.stderr)
            return 2
        k, v = f.split("=", 1)
        filters[k.strip()] = v.strip()

    sql, cols, rows = run_metric(args.metric, filters, args.by)
    m = registry["metrics"][args.metric]

    if args.show_sql:
        print("-- compiled SQL --")
        print(sql.strip(), "\n")

    print(f"{m['label']}  [{m['unit']}]")
    if args.by:
        width = max((len(str(r[0])) for r in rows), default=8)
        for r in rows:
            print(f"  {str(r[0]):<{width}}  {r[1]:>14,.2f}" if isinstance(r[1], float)
                  else f"  {str(r[0]):<{width}}  {r[1]:>14}")
    else:
        val = rows[0][0] if rows else None
        if isinstance(val, float):
            print(f"  {val:,.2f}")
        else:
            print(f"  {val}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
