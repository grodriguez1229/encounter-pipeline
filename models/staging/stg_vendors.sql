SELECT
    vendor_id,
    vendor_name,
    npi,
    tax_id,
    zip
FROM {{ source('raw', 'vendors') }}
