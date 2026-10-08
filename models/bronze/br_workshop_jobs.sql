-- Bronze: typed read of the workshop (service work-order) extract, as-is.
select
    job_id,
    cast(created_ts as timestamp)                  as created_ts,
    try_cast(completed_ts as timestamp)            as completed_ts,
    cast(store_id as integer)                      as store_id,
    channel                                        as channel_raw,
    customer_id,
    cast(labor_hours as decimal(8,2))              as labor_hours,
    cast(labor_rate as decimal(8,2))               as labor_rate,
    cast(parts_cost as decimal(12,2))              as parts_cost,
    cast(invoice_amount as decimal(12,2))          as invoice_amount,
    status
from read_csv_auto('{{ var("raw_dir") }}/workshop_jobs.csv', header = true)
