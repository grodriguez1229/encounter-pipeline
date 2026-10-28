-- Plain-English labels for the rejection codes this pipeline sees. In a dbt project
-- this would be a seed (CSV). Wording is from the X12 claim status code lists.
SELECT * FROM (VALUES
    ('IK5:5',     '999', 'File rejected: one or more segments in error'),
    ('A7:562:85', '277CA', 'Billing provider NPI invalid'),
    ('A7:500:PW', '277CA', 'Pickup ZIP invalid'),
    ('A7:500:45', '277CA', 'Dropoff ZIP invalid'),
    ('A7:187',    '277CA', 'Date of service invalid'),
    ('A3:109:IL', '277CA', 'Member not eligible'),
    ('A3:33',     '277CA', 'Member not found'),
    ('A3:54',     '277CA', 'Duplicate of a processed claim'),
    ('A7:464',    '277CA', 'Unknown payer claim number on replacement')
) AS t(status_code, response_type, description)
