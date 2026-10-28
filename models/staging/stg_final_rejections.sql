SELECT
    trip_id,
    submission_id,
    status_codes,
    reason,
    decided_at
FROM {{ source('raw', 'final_rejections') }}
