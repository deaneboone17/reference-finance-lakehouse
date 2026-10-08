# Reference Finance-Data Lakehouse

A small, fully local reference implementation of the data architecture I use to
turn messy multi-system operational data into governed, trustworthy finance
metrics — including a **burdened cost-per-sale** attribution model.

Everything here runs on your laptop with **DuckDB** and **dbt**. No cloud, no
credentials, no network calls. All data is **synthetic**, generated
deterministically for a fictional company, **Meridian Cycle Co.** — a
multi-location bicycle retail and service business.

The point of the repo is the *pattern*, not the numbers: how to take four
independent source systems, reconcile them through a medallion lakehouse,
define every KPI once in a registry, and put a natural-language layer on top
that **retrieves governed metrics instead of calculating its own**.

---

## The idea in one picture

```
  SOURCE SYSTEMS (synthetic)         LAKEHOUSE (dbt + DuckDB)            CONSUMPTION
  ────────────────────────          ──────────────────────────         ───────────────────────

  pos_orders.csv      ─┐            ┌──────────┐                        ┌─────────────────────┐
  (retail POS)         │            │  BRONZE  │  typed 1:1 reads       │  KPI REGISTRY       │
                       │            │          │  (lineage, no logic)   │  metrics.yml        │
  workshop_jobs.csv   ─┼──ingest──▶ ├──────────┤                        │  every metric = SQL │
  (service orders)     │            │  SILVER  │  conform channels,     │  defined ONCE       │
                       │            │          │  unify to one "sale"   └──────────┬──────────┘
  ad_spend.csv        ─┤            ├──────────┤  grain, dedupe                    │
  (marketing spend)    │            │   GOLD   │  facts, dims,          ┌──────────▼──────────┐
                       │            │          │  attribution mart      │  AI RETRIEVAL LAYER │
  crm_leads.csv       ─┘            └──────────┘  (burdened CPS)        │  NL → pick a metric │
  (CRM leads)                                                           │  → registry runs SQL│
                                                                        │  model never does   │
                                                                        │  the arithmetic     │
                                                                        └─────────────────────┘
```

## Architecture principles

1. **Medallion layering (bronze → silver → gold).** Bronze lands each source
   system exactly as-is (typed, no business logic) so lineage is auditable.
   Silver conforms and reconciles — this is where four systems that spell
   "paid search" five different ways, and two systems that both represent "a
   sale," become one consistent grain. Gold holds the facts, dimensions, and
   marts that the business actually reads.

2. **One reconciliation seam.** Retail orders and service jobs are two
   different source systems with different schemas. They are unified into a
   single `sv_sales` grain exactly once. Nothing downstream needs to know a
   sale came from two places — which is the whole job of a reconciliation
   layer.

3. **A KPI registry is the single source of truth.** Every metric —
   `total_revenue`, `average_ticket`, `burdened_cost_per_sale` — is defined
   once, in `registry/metrics.yml`, as SQL over the gold layer. Dashboards,
   exports, and the AI layer all read the same definitions, so "revenue"
   cannot quietly mean three different things in three different places.

4. **AI retrieves, never calculates.** The natural-language layer lets a model
   decide *which* registry metric answers a question and *which* filters to
   apply. The number itself is always computed in SQL by the registry. The
   model cannot hallucinate a KPI or do its own math, so every answer is
   reproducible and matches the dashboards.

5. **Costs are burdened, not just media.** The attribution mart separates
   *media cost per sale* (ad spend ÷ sales) from *burdened cost per sale*
   (media **plus** fully-loaded labor **plus** allocated overhead ÷ sales).
   A channel with zero ad spend is not free — it still consumes shop labor and
   a share of fixed overhead. Burdening is what makes channels comparable on a
   true-cost basis.

## Layout

```
reference-lakehouse/
├── generate_data.py           # deterministic synthetic data generator (4 source CSVs)
├── dbt_project.yml            # dbt config + business vars (loaded labor rate, overhead)
├── profiles.yml               # local DuckDB profile (one file, no cloud)
├── models/
│   ├── bronze/                # typed 1:1 reads of each source extract
│   ├── silver/                # conformed, reconciled, unified grain
│   └── gold/                  # fct_sales, fct_ad_spend, dim_channel,
│                              #   mart_channel_performance (the attribution rollup)
├── macros/                    # channel conforming + schema naming
├── tests/                     # invariant guard (burdened ≥ media cost per sale)
├── registry/
│   ├── metrics.yml            # the KPI registry — every metric, defined once
│   └── query.py               # compiles a registry metric to SQL and runs it
├── ai_query/
│   └── ask.py                 # NL → retrieval plan → registry runs the SQL
└── run.sh                     # the whole pipeline, end to end
```

## Quickstart

Requires Python 3.9+.

```bash
# 1. set up an isolated environment
python3 -m venv .venv           # or: uv venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. run the whole thing: generate → build → query → ask
./run.sh
```

`run.sh` is just these four steps, which you can also run by hand:

```bash
# generate the four synthetic source extracts into data/raw/
python generate_data.py

# build the lakehouse (bronze → silver → gold) and run the tests
dbt build --profiles-dir .

# ask the KPI registry for a governed metric
python registry/query.py --list                                  # the metric catalog
python registry/query.py burdened_cost_per_sale --by channel
python registry/query.py total_revenue --by store
python registry/query.py total_revenue --filter channel=paid_search --show-sql

# ask in plain English (the model picks the metric; SQL computes it)
python ai_query/ask.py --catalog                                 # what a real LLM is handed
python ai_query/ask.py "show me burdened cost per sale by channel"
python ai_query/ask.py "what was total revenue from paid search"
```

## What the attribution mart shows

Running against the generated data, `mart_channel_performance` makes the
media-vs-burdened gap obvious. A paid channel can look cheap on media alone yet
cost far more once labor and overhead are loaded in; a zero-media channel is
never actually free:

| channel        | media cost/sale | burdened cost/sale |
|----------------|----------------:|-------------------:|
| paid_social    |          ~$85   |             ~$126  |
| paid_search    |          ~$82   |             ~$123  |
| email          |          ~$37   |              ~$77  |
| referral       |           $0    |              ~$42  |
| organic_search |           $0    |              ~$40  |
| walk_in        |           $0    |              ~$40  |

(Exact figures are reproducible from the fixed seed; this is the shape of the
result.)

## Extending it

- **Add a metric:** add an entry to `registry/metrics.yml`. It is immediately
  available to `registry/query.py` and `ai_query/ask.py` — no other code
  changes.
- **Add a source system:** drop a bronze model that reads the new extract,
  conform it in silver, join it into the relevant gold mart.
- **Swap in a real LLM:** replace `plan_from_question()` in `ai_query/ask.py`
  with a constrained model call. Give it the `--catalog` output and the
  question; have it return `{"metric", "filters", "by"}`. The contract — and
  the "never calculates" guarantee — stays identical.

---

*Synthetic data only. Meridian Cycle Co. is fictional; any resemblance to a
real business is coincidental.*
