SELECT
    submission_id,
    file_name,
    plan_id,
    isa13,
    gs06,
    st02,
    claim_count,
    created_at AS submitted_at
FROM {{ source('raw', 'submissions') }}
