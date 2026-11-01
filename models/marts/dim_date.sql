-- Every day from the first trip through run_date.
SELECT
    d::DATE AS date_day,
    date_trunc('month', d)::DATE AS month_start,
    year(d) AS year,
    month(d) AS month,
    dayname(d) AS day_name,
    isodow(d) IN (6, 7) AS is_weekend
FROM range(
    (SELECT min(trip_date) FROM {{ ref('stg_trips') }}),
    DATE '{{ var('run_date') }}' + INTERVAL 1 DAY,
    INTERVAL 1 DAY
) AS t(d)
