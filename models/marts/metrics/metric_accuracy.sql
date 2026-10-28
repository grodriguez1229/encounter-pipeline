-- How often the first submission was accepted, and how often fixes worked.
-- Duplicates count here: we sent them, and they were wrong.
SELECT
    CASE WHEN grouping(plan_id) = 1 THEN 'All plans' ELSE plan_id END AS plan_id,
    count(*) FILTER (WHERE first_submitted_at IS NOT NULL) AS submitted,
    count(*) FILTER (WHERE first_pass_status IN ('accepted', 'rejected')) AS first_pass_responded,
    count(*) FILTER (WHERE first_pass_status = 'accepted') AS first_pass_accepted,
    count(*) FILTER (WHERE first_pass_status = 'rejected' AND first_pass_response_type = '999')
        AS first_pass_rejected_999,
    count(*) FILTER (WHERE first_pass_status = 'rejected' AND first_pass_response_type = '277CA')
        AS first_pass_rejected_277ca,
    round(100.0 * count(*) FILTER (WHERE first_pass_status = 'accepted')
        / count(*) FILTER (WHERE first_pass_status IN ('accepted', 'rejected')), 1)
        AS first_pass_acceptance_pct,
    count(*) FILTER (WHERE original_count > 1) AS resubmitted,
    count(*) FILTER (WHERE original_count > 1 AND current_status = 'accepted')
        AS resubmitted_accepted,
    round(100.0 * count(*) FILTER (WHERE original_count > 1 AND current_status = 'accepted')
        / nullif(count(*) FILTER (WHERE original_count > 1), 0), 1) AS resubmit_success_pct
FROM {{ ref('fct_encounter') }}
GROUP BY GROUPING SETS ((plan_id), ())
