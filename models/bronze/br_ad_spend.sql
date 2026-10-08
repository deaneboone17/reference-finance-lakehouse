-- Bronze: typed read of the marketing spend extract, as-is.
select
    cast(spend_date as date)             as spend_date,
    cast(store_id as integer)            as store_id,
    channel                              as channel_raw,
    cast(spend as decimal(12,2))         as spend,
    cast(impressions as integer)         as impressions,
    cast(clicks as integer)              as clicks
from read_csv_auto('{{ var("raw_dir") }}/ad_spend.csv', header = true)
