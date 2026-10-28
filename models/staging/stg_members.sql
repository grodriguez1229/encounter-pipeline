SELECT
    member_id,
    plan_id,
    first_name,
    last_name,
    birth_date,
    gender,
    zip,
    eligibility_start,
    eligibility_end
FROM {{ source('raw', 'members') }}
