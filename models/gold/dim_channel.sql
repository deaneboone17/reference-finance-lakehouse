-- Gold: the conformed channel dimension, with a paid-media flag.
with channels as (
    select distinct channel from {{ ref('sv_sales') }}
)
select
    channel,
    channel in ('paid_search', 'paid_social', 'email') as is_paid_media
from channels
order by channel
