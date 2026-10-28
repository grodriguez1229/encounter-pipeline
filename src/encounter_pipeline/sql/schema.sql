-- Raw and operational tables. Each pipeline step adds its tables here as it gets built.
-- Everything is CREATE IF NOT EXISTS so connecting twice is harmless.

-- Last control number used per type (ISA13, GS06, ST02), so numbers keep
-- incrementing across runs instead of restarting at 1.
CREATE TABLE IF NOT EXISTS control_numbers (
    kind VARCHAR PRIMARY KEY,
    last_value BIGINT NOT NULL
);
