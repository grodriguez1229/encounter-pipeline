SELECT
    trip_id,
    submission_id,
    source AS response_type,
    status,
    status_codes,
    -- First status composite split into its parts, e.g. A7:562:85 -> A7, 562, 85.
    split_part(status_codes, ',', 1) AS primary_status_code,
    split_part(split_part(status_codes, ',', 1), ':', 1) AS status_category,
    payer_claim_number,
    response_file,
    received_at
FROM {{ source('raw', 'claim_status_history') }}
