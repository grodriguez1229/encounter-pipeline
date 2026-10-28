SELECT
    submission_id,
    trip_id,
    frequency_code,
    CASE frequency_code
        WHEN '1' THEN 'original'
        WHEN '7' THEN 'replacement'
        WHEN '8' THEN 'void'
    END AS submission_type,
    payer_claim_number AS replaces_payer_claim_number,
    line_count,
    charge
FROM {{ source('raw', 'submission_claims') }}
