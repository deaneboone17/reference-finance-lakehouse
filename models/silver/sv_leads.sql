-- Silver: conformed CRM leads with a clean won flag.
select
    lead_id,
    created_ts,
    cast(created_ts as date)              as created_date,
    store_id,
    {{ store_name('store_id') }}          as store_name,
    {{ conform_channel('channel_raw') }}  as channel,
    status,
    converted_sale_id,
    (status = 'won')                      as is_won
from {{ ref('br_crm_leads') }}
