-- Raw and operational tables. Each pipeline step adds its tables here as it gets built.
-- Everything is CREATE IF NOT EXISTS so connecting twice is harmless.

-- Last control number used per type (ISA13, GS06, ST02), so numbers keep
-- incrementing across runs instead of restarting at 1.
CREATE TABLE IF NOT EXISTS control_numbers (
    kind VARCHAR PRIMARY KEY,
    last_value BIGINT NOT NULL
);

-- Synthetic source data, written by `generate`.

CREATE TABLE IF NOT EXISTS plans (
    plan_id VARCHAR PRIMARY KEY,
    plan_name VARCHAR NOT NULL,
    line_of_business VARCHAR NOT NULL,  -- MA or MEDICAID
    payer_id VARCHAR NOT NULL           -- goes in the 837 payer loop (2010BB NM109)
);

CREATE TABLE IF NOT EXISTS members (
    member_id VARCHAR PRIMARY KEY,
    plan_id VARCHAR NOT NULL,
    first_name VARCHAR NOT NULL,
    last_name VARCHAR NOT NULL,
    birth_date DATE NOT NULL,
    gender VARCHAR NOT NULL,            -- F, M or U, same codes as X12 DMG03
    address1 VARCHAR NOT NULL,
    city VARCHAR NOT NULL,
    state VARCHAR NOT NULL,
    zip VARCHAR NOT NULL,
    eligibility_start DATE NOT NULL,
    eligibility_end DATE                -- NULL = still eligible
);

CREATE TABLE IF NOT EXISTS vendors (
    vendor_id VARCHAR PRIMARY KEY,
    vendor_name VARCHAR NOT NULL,
    npi VARCHAR,                        -- nullable: "missing NPI" is one of the injected problems
    tax_id VARCHAR NOT NULL,
    address1 VARCHAR NOT NULL,
    city VARCHAR NOT NULL,
    state VARCHAR NOT NULL,
    zip VARCHAR NOT NULL
);
