SELECT
    plan_id,
    plan_name,
    line_of_business,
    payer_id
FROM {{ source('raw', 'plans') }}
