-- One row per submitted trip: how its first submission did, when it was first accepted,
-- and where it stands now.
WITH first_pass AS (
    SELECT h.trip_id, h.status, h.status_codes, h.response_type, h.received_at
    FROM {{ ref('int_trip_submissions') }} ts
    JOIN {{ ref('stg_claim_status_history') }} h
        ON h.trip_id = ts.trip_id AND h.submission_id = ts.first_submission_id
),

latest AS (
    SELECT h.trip_id, h.status
    FROM {{ ref('int_trip_submissions') }} ts
    JOIN {{ ref('stg_claim_status_history') }} h
        ON h.trip_id = ts.trip_id AND h.submission_id = ts.latest_submission_id
),

accepted AS (
    SELECT
        trip_id,
        min(received_at) AS accepted_at,
        arg_max(payer_claim_number, received_at) AS payer_claim_number
    FROM {{ ref('stg_claim_status_history') }}
    WHERE status = 'accepted'
    GROUP BY trip_id
)

SELECT
    ts.trip_id,
    fp.status AS first_pass_status,
    fp.response_type AS first_pass_response_type,
    fp.status_codes AS first_pass_codes,
    a.accepted_at,
    a.payer_claim_number,
    f.reason AS final_rejection_reason,
    coalesce(f.status_codes = 'A3:54', false) AS is_duplicate,
    -- Once accepted, a trip stays accepted: a later replacement that's still out (or
    -- even rejected) doesn't undo the original acceptance.
    CASE
        WHEN a.accepted_at IS NOT NULL THEN 'accepted'
        WHEN f.trip_id IS NOT NULL THEN 'rejected_final'
        WHEN l.status = 'rejected' THEN 'rejected_open'
        ELSE 'awaiting_response'
    END AS current_status
FROM {{ ref('int_trip_submissions') }} ts
LEFT JOIN first_pass fp USING (trip_id)
LEFT JOIN latest l USING (trip_id)
LEFT JOIN accepted a USING (trip_id)
LEFT JOIN {{ ref('stg_final_rejections') }} f USING (trip_id)
