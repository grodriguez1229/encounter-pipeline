-- One row per completed trip: the encounter we owe the plan, and where it stands.
SELECT
    t.trip_id,
    t.member_id,
    m.plan_id,
    t.vendor_id,
    t.trip_date,
    t.trip_month,
    t.level_of_service,
    t.reported_date,
    ts.first_submitted_at,
    s.accepted_at,
    coalesce(s.current_status, 'not_submitted') AS current_status,
    s.first_pass_status,
    s.first_pass_response_type,
    s.first_pass_codes,
    s.final_rejection_reason,
    coalesce(s.is_duplicate, false) AS is_duplicate,
    coalesce(ts.original_count, 0) AS original_count,
    coalesce(ts.replacement_count, 0) AS replacement_count,
    date_diff('day', t.trip_date, ts.first_submitted_at::DATE) AS days_to_submit,
    date_diff('day', t.trip_date, s.accepted_at::DATE) AS days_to_accept,
    -- Late = first submitted after the deadline, or not submitted and already past it.
    coalesce(ts.first_submitted_at::DATE, DATE {{ var('run_date') }})
        > t.trip_date + {{ var('submission_deadline_days') }} AS past_deadline
FROM {{ ref('stg_trips') }} t
JOIN {{ ref('stg_members') }} m USING (member_id)
LEFT JOIN {{ ref('int_trip_submissions') }} ts USING (trip_id)
LEFT JOIN {{ ref('int_trip_status') }} s USING (trip_id)
WHERE t.trip_status = 'completed'
