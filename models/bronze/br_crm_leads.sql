-- Bronze: typed read of the CRM lead extract, as-is.
select
    lead_id,
    cast(created_ts as timestamp)   as created_ts,
    cast(store_id as integer)       as store_id,
    channel                         as channel_raw,
    status,
    nullif(converted_sale_id, '')   as converted_sale_id
from read_csv_auto('{{ var("raw_dir") }}/crm_leads.csv', header = true)
