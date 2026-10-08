-- Bronze: a faithful, typed read of the point-of-sale extract. No business
-- logic here; bronze only lands the source system as-is so lineage is auditable.
select
    order_id,
    cast(order_ts as timestamp)      as order_ts,
    cast(store_id as integer)        as store_id,
    channel                          as channel_raw,
    customer_id,
    cast(gross_amount as decimal(12,2))    as gross_amount,
    cast(discount_amount as decimal(12,2)) as discount_amount,
    cast(cogs as decimal(12,2))            as cogs
from read_csv_auto('{{ var("raw_dir") }}/pos_orders.csv', header = true)
