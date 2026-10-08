# Architecture notes

## Data flow

```
 generate_data.py
      │  writes 4 CSV "source system" extracts
      ▼
 data/raw/{pos_orders, workshop_jobs, ad_spend, crm_leads}.csv
      │  read_csv_auto (typed, 1:1)
      ▼
 BRONZE   br_pos_orders · br_workshop_jobs · br_ad_spend · br_crm_leads     (views)
      │  conform_channel() macro · store_name() macro · union retail+service · dedupe
      ▼
 SILVER   sv_sales (unified grain) · sv_ad_spend · sv_leads                 (views)
      │  add burdened labor cost · build facts/dims · allocate overhead
      ▼
 GOLD     fct_sales · fct_ad_spend · dim_channel · mart_channel_performance (tables)
      │
      ├────────────▶ registry/metrics.yml  (KPI definitions, SQL over gold.*)
      │                      │
      │                      ├──▶ registry/query.py  (CLI / library)
      │                      └──▶ ai_query/ask.py     (NL → plan → registry SQL)
```

## Model inventory

| Layer  | Model                      | Grain                         | Materialized |
|--------|----------------------------|-------------------------------|--------------|
| bronze | `br_pos_orders`            | one retail order              | view         |
| bronze | `br_workshop_jobs`         | one service job               | view         |
| bronze | `br_ad_spend`              | day × store × channel         | view         |
| bronze | `br_crm_leads`             | one lead                      | view         |
| silver | `sv_sales`                 | one sale (retail ∪ service)   | view         |
| silver | `sv_ad_spend`              | day × store × channel         | view         |
| silver | `sv_leads`                 | one lead                      | view         |
| gold   | `fct_sales`                | one sale + burdened labor     | table        |
| gold   | `fct_ad_spend`             | day × store × channel         | table        |
| gold   | `dim_channel`              | one channel                   | table        |
| gold   | `mart_channel_performance` | one channel (period rollup)   | table        |

## Key business rules (and where they live)

- **Channel conforming** — `macros/conform_channel.sql`. One place maps every
  raw spelling to a canonical channel.
- **What counts as a sale** — `models/silver/sv_sales.sql`. Retail orders plus
  *completed* service jobs; cancelled jobs are excluded; sales are deduped by
  key so a replayed extract can't double-count.
- **Burdened labor cost** — `fct_sales.labor_cost = labor_hours ×
  labor_loaded_rate` (var in `dbt_project.yml`). The loaded rate is the true
  cost to the business, deliberately higher than the rate billed to the
  customer.
- **Overhead allocation** — `mart_channel_performance`. A fixed period
  overhead (`period_overhead` var) is spread across channels pro-rata by share
  of sales.
- **Invariant guard** — `tests/assert_burdened_ge_media.sql`. Burdened cost
  per sale can never fall below media-only cost per sale; dbt fails the build
  if it ever does.

## Why DuckDB here

DuckDB makes the whole warehouse a single local file and needs no server, so
the reference implementation is genuinely clone-and-run. The same dbt models
and the same KPI registry port directly to a columnar cloud warehouse by
changing only the dbt profile — the modeling pattern is the transferable part.
