-- One row per status event (999 or 277CA) for every claim we sent.
SELECT
    h.trip_id,
    h.submission_id,
    s.plan_id,
    sc.submission_type,
    s.submitted_at,
    h.response_type,
    h.status,
    h.status_codes,
    h.primary_status_code,
    h.status_category,
    c.description AS status_description,
    h.payer_claim_number,
    h.received_at,
    date_diff('hour', s.submitted_at, h.received_at) AS hours_to_response
FROM {{ ref('stg_claim_status_history') }} h
JOIN {{ ref('stg_submissions') }} s USING (submission_id)
JOIN {{ ref('stg_submission_claims') }} sc USING (submission_id, trip_id)
LEFT JOIN {{ ref('stg_status_codes') }} c ON c.status_code = h.primary_status_code
