-- Days from trip to first submission and to first acceptance, and trips past the
-- submission deadline (submitted late, or still unsubmitted and already overdue).
SELECT
    CASE WHEN grouping(plan_id) = 1 THEN 'All plans' ELSE plan_id END AS plan_id,
    count(*) AS completed_trips,
    median(days_to_submit) AS median_days_to_submit,
    quantile_cont(days_to_submit, 0.9) AS p90_days_to_submit,
    median(days_to_accept) AS median_days_to_accept,
    quantile_cont(days_to_accept, 0.9) AS p90_days_to_accept,
    count(*) FILTER (WHERE past_deadline) AS past_deadline,
    round(100.0 * count(*) FILTER (WHERE past_deadline) / count(*), 1) AS past_deadline_pct
FROM {{ ref('fct_encounter') }}
WHERE NOT is_duplicate
GROUP BY GROUPING SETS ((plan_id), ())
