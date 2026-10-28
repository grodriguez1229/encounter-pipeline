SELECT
    m.*,
    p.plan_name,
    p.line_of_business
FROM {{ ref('stg_members') }} m
JOIN {{ ref('stg_plans') }} p USING (plan_id)
