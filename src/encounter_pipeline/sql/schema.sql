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

-- One row per ride leg. Only completed trips become encounters.
CREATE TABLE IF NOT EXISTS trips (
    trip_id VARCHAR PRIMARY KEY,
    member_id VARCHAR NOT NULL,
    vendor_id VARCHAR NOT NULL,
    trip_date DATE NOT NULL,
    origin_type VARCHAR NOT NULL,       -- one-letter origin code, first half of the HCPCS modifier
    pickup_address1 VARCHAR NOT NULL,
    pickup_city VARCHAR NOT NULL,
    pickup_state VARCHAR NOT NULL,
    pickup_zip VARCHAR NOT NULL,
    destination_type VARCHAR NOT NULL,  -- one-letter destination code, second half of the modifier
    dropoff_address1 VARCHAR NOT NULL,
    dropoff_city VARCHAR NOT NULL,
    dropoff_state VARCHAR NOT NULL,
    dropoff_zip VARCHAR NOT NULL,
    level_of_service VARCHAR NOT NULL,  -- ambulatory, wheelchair, stretcher
    loaded_miles DECIMAL(6, 1) NOT NULL,
    status VARCHAR NOT NULL,            -- completed, cancelled, no_show
    reported_date DATE NOT NULL         -- when the vendor confirmed the ride; it's submitted the night after
);

-- Answer key for the problems `generate` broke on purpose. The pipeline never reads
-- this; tests use it to check the payer caught the right things, and resubmit uses
-- original_value to simulate an ops fix.
CREATE TABLE IF NOT EXISTS injected_problems (
    trip_id VARCHAR PRIMARY KEY,
    problem VARCHAR NOT NULL,
    original_value VARCHAR             -- what the field was before we broke it
);

-- One row per outbound 837 file. Each file has one ISA, one GS and one ST, so the
-- three control numbers identify it; responses come back pointing at them.
CREATE TABLE IF NOT EXISTS submissions (
    submission_id BIGINT PRIMARY KEY,   -- same as isa13, which is unique per file
    file_name VARCHAR NOT NULL,
    plan_id VARCHAR NOT NULL,
    isa13 BIGINT NOT NULL,
    gs06 BIGINT NOT NULL,
    st02 VARCHAR NOT NULL,
    claim_count INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL
);

-- Which trips went out in which file. A trip shows up again when it's resubmitted.
CREATE TABLE IF NOT EXISTS submission_claims (
    submission_id BIGINT NOT NULL,
    trip_id VARCHAR NOT NULL,
    frequency_code VARCHAR NOT NULL,    -- CLM05-3: 1 original, 7 replacement
    payer_claim_number VARCHAR,         -- REF*F8 on replacements
    line_count INTEGER NOT NULL,
    charge DECIMAL(10, 2) NOT NULL,
    PRIMARY KEY (submission_id, trip_id)
);

-- Every response file we've loaded, raw text included, so a load can be re-checked later.
CREATE TABLE IF NOT EXISTS response_files (
    file_name VARCHAR PRIMARY KEY,
    file_type VARCHAR NOT NULL,         -- 999 or 277CA
    isa13 BIGINT NOT NULL,              -- the payer's interchange number
    received_at TIMESTAMP NOT NULL,     -- ISA09/ISA10, standing in for when it landed
    raw_text VARCHAR NOT NULL
);

-- 999 verdicts, one per outbound transaction set (here, one per file).
CREATE TABLE IF NOT EXISTS submission_acks (
    submission_id BIGINT NOT NULL,
    response_file VARCHAR NOT NULL,
    accepted BOOLEAN NOT NULL,
    codes VARCHAR,                      -- IK502+ reasons, comma separated
    errors VARCHAR,                     -- IK3/IK4 details, semicolon separated
    received_at TIMESTAMP NOT NULL
);

-- Every status event for every claim, never updated. A 999 rejection writes a row for
-- each claim in the rejected file; a 277CA writes one row per claim it mentions.
CREATE TABLE IF NOT EXISTS claim_status_history (
    trip_id VARCHAR NOT NULL,
    submission_id BIGINT NOT NULL,
    source VARCHAR NOT NULL,            -- 999 or 277CA
    status VARCHAR NOT NULL,            -- accepted, rejected or pending
    status_codes VARCHAR,               -- STC composites, comma separated, e.g. A7:562:85
    payer_claim_number VARCHAR,
    response_file VARCHAR NOT NULL,
    received_at TIMESTAMP NOT NULL
);

-- Responses we couldn't tie back to anything we sent. Kept instead of failing the load.
CREATE TABLE IF NOT EXISTS quarantine (
    response_file VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    detail VARCHAR,
    received_at TIMESTAMP NOT NULL
);
