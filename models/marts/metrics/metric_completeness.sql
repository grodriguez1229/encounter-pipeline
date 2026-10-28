-- Share of completed trips with an accepted encounter, by plan and month, plus totals.
-- Duplicate copies are left out: they're the same ride, not another one we owe.
SELECT
    CASE WHEN grouping(plan_id) = 1 THEN 'All plans' ELSE plan_id END AS plan_id,
    trip_month,                           -- NULL on rows that total across months
    count(*) AS completed_trips,
    count(*) FILTER (WHERE current_status = 'accepted') AS accepted,
    count(*) FILTER (WHERE current_status = 'awaiting_response') AS awaiting_response,
    count(*) FILTER (WHERE current_status = 'rejected_open') AS rejected_open,
    count(*) FILTER (WHERE current_status = 'rejected_final') AS rejected_final,
    count(*) FILTER (WHERE current_status = 'not_submitted') AS not_submitted,
    round(100.0 * count(*) FILTER (WHERE current_status = 'accepted') / count(*), 1)
        AS completeness_pct
FROM {{ ref('fct_encounter') }}
WHERE NOT is_duplicate
GROUP BY GROUPING SETS ((plan_id, trip_month), (plan_id), (trip_month), ())
