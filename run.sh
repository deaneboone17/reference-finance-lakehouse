#!/usr/bin/env bash
# End-to-end: unit tests -> generate synthetic data -> build the medallion
# lakehouse -> run sample registry queries -> run the AI-retrieval demo.
# Uses the offline stub planner, so it needs no credentials or network.
# Safe to run repeatedly; it rebuilds from scratch each time.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python}"

echo "==> 1/5  Unit tests (plan validator + planners, offline)"
"$PY" -m unittest discover -s ai_query/tests -t .

echo
echo "==> 2/5  Generating synthetic source data"
"$PY" generate_data.py

echo
echo "==> 3/5  Building the lakehouse (dbt: bronze -> silver -> gold, + tests)"
dbt build --profiles-dir .

echo
echo "==> 4/5  Sample KPI-registry queries"
"$PY" registry/query.py burdened_cost_per_sale --by channel
echo
"$PY" registry/query.py total_revenue --by store

echo
echo "==> 5/5  AI retrieval demo (the planner picks the metric; SQL computes it)"
RFL_PLANNER=stub "$PY" ai_query/ask.py "show me burdened cost per sale by channel"
echo
RFL_PLANNER=stub "$PY" ai_query/ask.py "what was total revenue from paid search"

echo
echo "Done. Warehouse: ./warehouse.duckdb"
