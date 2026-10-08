-- Silver: conformed marketing spend, channel names reconciled to canonical.
select
    spend_date,
    strftime(spend_date, '%Y-%m')        as spend_month,
    store_id,
    {{ store_name('store_id') }}         as store_name,
    {{ conform_channel('channel_raw') }} as channel,
    spend,
    impressions,
    clicks
from {{ ref('br_ad_spend') }}
