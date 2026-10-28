-- One row per submitted trip: when it first went out, how many times, and its latest submission.
SELECT
    sc.trip_id,
    min(s.submitted_at) AS first_submitted_at,
    arg_min(sc.submission_id, s.submitted_at) AS first_submission_id,
    arg_max(sc.submission_id, s.submitted_at) AS latest_submission_id,
    count(*) FILTER (WHERE sc.submission_type = 'original') AS original_count,
    count(*) FILTER (WHERE sc.submission_type = 'replacement') AS replacement_count
FROM {{ ref('stg_submission_claims') }} sc
JOIN {{ ref('stg_submissions') }} s USING (submission_id)
GROUP BY sc.trip_id
