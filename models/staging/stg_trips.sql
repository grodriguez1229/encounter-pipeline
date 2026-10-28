SELECT
    trip_id,
    member_id,
    vendor_id,
    trip_date,
    date_trunc('month', trip_date)::DATE AS trip_month,
    level_of_service,
    origin_type || destination_type AS modifier,
    loaded_miles,
    status AS trip_status,
    reported_date
FROM {{ source('raw', 'trips') }}
