-- Every rejection we got back, by code.
SELECT
    response_type,
    primary_status_code AS status_code,
    status_description,
    count(*) AS rejections,
    count(DISTINCT trip_id) AS trips
FROM {{ ref('fct_claim_status') }}
WHERE status = 'rejected'
GROUP BY ALL
