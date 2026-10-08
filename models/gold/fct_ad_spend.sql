-- Gold: marketing spend fact at day / store / channel grain.
select
    spend_date,
    spend_month,
    store_id,
    store_name,
    channel,
    spend,
    impressions,
    clicks
from {{ ref('sv_ad_spend') }}
