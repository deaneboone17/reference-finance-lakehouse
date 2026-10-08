-- Invariant guard: a fully-burdened cost per sale can never be cheaper than
-- the media-only cost per sale. If this test returns any rows, the burden
-- logic is broken. (dbt treats a passing test as returning zero rows.)
select channel, media_cost_per_sale, burdened_cost_per_sale
from {{ ref('mart_channel_performance') }}
where burdened_cost_per_sale < media_cost_per_sale
