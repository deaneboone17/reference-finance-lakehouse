#!/usr/bin/env bash
# End-to-end: generate synthetic data -> build the medallion lakehouse ->
# run a sample registry query -> run the AI-retrieval demo.
# Safe to run repeatedly; it rebuilds from scratch each time.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python}"

echo "==> 1/4  Generating synthetic source data"
"$PY" generate_data.py

echo
echo "==> 2/4  Building the lakehouse (dbt: bronze -> silver -> gold, + tests)"
dbt build --profiles-dir .

echo
echo "==> 3/4  Sample KPI-registry queries"
"$PY" registry/query.py burdened_cost_per_sale --by channel
echo
"$PY" registry/query.py total_revenue --by store

echo
echo "==> 4/4  AI retrieval demo (model selects the metric; SQL computes it)"
"$PY" ai_query/ask.py "show me burdened cost per sale by channel"
echo
"$PY" ai_query/ask.py "what was total revenue from paid search"

echo
echo "Done. Warehouse: ./warehouse.duckdb"
