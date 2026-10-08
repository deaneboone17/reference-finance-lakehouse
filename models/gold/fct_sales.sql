-- Gold: the sales fact, one row per sale, enriched with fully-burdened labor
-- cost. labor_cost uses the loaded shop rate (wages + taxes + benefits +
-- idle time), which is deliberately different from the rate billed to the
-- customer -- that gap is the whole point of "burdened" economics.
select
    sale_id,
    sale_type,
    store_id,
    store_name,
    channel,
    sale_ts,
    sale_date,
    sale_month,
    net_revenue,
    direct_cost,
    labor_hours,
    round(labor_hours * {{ var('labor_loaded_rate') }}, 2) as labor_cost,
    gross_margin
from {{ ref('sv_sales') }}
