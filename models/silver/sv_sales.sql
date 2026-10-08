-- Silver: one conformed grain of "a sale", unifying two different source
-- systems (retail point-of-sale and workshop service jobs) into a single
-- shape. Channel is conformed, stores are named, revenue is defined
-- consistently, and cancelled service jobs are dropped. This is the
-- reconciliation seam: downstream, nobody needs to know a sale came from two
-- systems with different column names.

with retail as (
    select
        order_id                                   as sale_id,
        'retail'                                   as sale_type,
        store_id,
        {{ conform_channel('channel_raw') }}       as channel,
        order_ts                                   as sale_ts,
        cast(order_ts as date)                     as sale_date,
        (gross_amount - discount_amount)           as net_revenue,
        cogs                                       as direct_cost,
        0.00                                       as labor_hours
    from {{ ref('br_pos_orders') }}
),

service as (
    select
        job_id                                     as sale_id,
        'service'                                  as sale_type,
        store_id,
        {{ conform_channel('channel_raw') }}       as channel,
        created_ts                                 as sale_ts,
        cast(created_ts as date)                   as sale_date,
        invoice_amount                             as net_revenue,
        parts_cost                                 as direct_cost,
        labor_hours
    from {{ ref('br_workshop_jobs') }}
    where status = 'completed'
),

unioned as (
    select * from retail
    union all
    select * from service
)

select
    sale_id,
    sale_type,
    store_id,
    {{ store_name('store_id') }}          as store_name,
    channel,
    sale_ts,
    sale_date,
    strftime(sale_date, '%Y-%m')          as sale_month,
    net_revenue,
    direct_cost,
    labor_hours,
    (net_revenue - direct_cost)           as gross_margin
from unioned
-- defensive dedupe: a replayed extract must never double-count a sale
qualify row_number() over (partition by sale_id order by sale_ts) = 1
