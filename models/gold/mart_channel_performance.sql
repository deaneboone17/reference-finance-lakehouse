-- Gold: the attribution rollup, one row per marketing channel for the whole
-- period. This is the headline mart -- it answers "what does a sale from this
-- channel actually cost us, once everything is loaded in?"
--
--   media_cost_per_sale     = media spend / sales            (the number most people stop at)
--   burdened_cost_per_sale  = (media + burdened labor + allocated overhead) / sales
--
-- A channel with zero media spend is not free: it still consumes shop labor
-- and a share of fixed overhead. Burdening is what surfaces that.

with sales as (
    select
        channel,
        count(*)            as sales_count,
        sum(net_revenue)    as revenue,
        sum(labor_cost)     as labor_cost
    from {{ ref('fct_sales') }}
    group by channel
),

media as (
    select channel, sum(spend) as media_cost
    from {{ ref('fct_ad_spend') }}
    group by channel
),

leads as (
    select
        channel,
        count(*)                      as leads,
        count(*) filter (where is_won) as won_leads
    from {{ ref('sv_leads') }}
    group by channel
),

total_sales as (
    select sum(sales_count) as all_sales from sales
)

select
    s.channel,
    c.is_paid_media,
    s.sales_count,
    round(s.revenue, 2)                                             as revenue,
    coalesce(round(m.media_cost, 2), 0.00)                          as media_cost,
    round(s.labor_cost, 2)                                          as labor_cost,
    -- fixed overhead allocated pro-rata by share of total sales
    round({{ var('period_overhead') }} * s.sales_count / t.all_sales, 2) as overhead_alloc,
    round(coalesce(m.media_cost, 0) / s.sales_count, 2)             as media_cost_per_sale,
    round(
        (coalesce(m.media_cost, 0)
         + s.labor_cost
         + {{ var('period_overhead') }} * s.sales_count / t.all_sales)
        / s.sales_count, 2)                                         as burdened_cost_per_sale,
    coalesce(l.leads, 0)                                            as leads,
    coalesce(l.won_leads, 0)                                        as won_leads,
    round(coalesce(l.won_leads, 0) * 100.0 / nullif(l.leads, 0), 1) as lead_to_sale_rate_pct
from sales s
cross join total_sales t
left join media m on s.channel = m.channel
left join leads l on s.channel = l.channel
left join {{ ref('dim_channel') }} c on s.channel = c.channel
order by burdened_cost_per_sale desc
