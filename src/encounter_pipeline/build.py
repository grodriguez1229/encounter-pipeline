"""build: turn completed trips into outbound 837P files.

Acts like a nightly job that has been running since the start of the data: each
trip goes out the night after the vendor reported it, batched by plan, at most
max_claims_per_file per file. Trips that were already submitted are skipped, so
re-running only picks up new work.
"""

from datetime import datetime, time, timedelta
from itertools import groupby

import duckdb

from encounter_pipeline.config import Config
from encounter_pipeline.x12 import writer_837
from encounter_pipeline.x12.envelope import build_interchange, next_control_number
from encounter_pipeline.x12.writer_837 import ClaimInput

NIGHTLY_RUN_TIME = time(2, 0)


def rows_as_dicts(con: duckdb.DuckDBPyConnection, sql: str, params=None) -> list[dict]:
    cursor = con.execute(sql, params or [])
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def pending_trips(con: duckdb.DuckDBPyConnection, config: Config) -> list[dict]:
    """Completed trips that were reported before the last nightly run and never submitted."""
    return rows_as_dicts(con, """
        SELECT t.*, m.plan_id
        FROM trips t
        JOIN members m USING (member_id)
        WHERE t.status = 'completed'
          AND t.reported_date < ?
          AND t.trip_id NOT IN (SELECT trip_id FROM submission_claims)
        ORDER BY t.reported_date, m.plan_id, t.vendor_id, t.member_id, t.trip_id
    """, [config.run_date])


def write_submission(
    con: duckdb.DuckDBPyConnection,
    config: Config,
    plan: dict,
    claims: list[ClaimInput],
    created: datetime,
) -> str:
    """Write one 837 file and record it. Returns the file name."""
    con.begin()
    batch_id = f"{plan['plan_id']}{created:%Y%m%d}"
    body = writer_837.transaction_body(claims, plan, batch_id, created)
    isa13 = next_control_number(con, "ISA")
    gs06 = next_control_number(con, "GS")
    st02 = f"{next_control_number(con, 'ST'):04d}"  # ST02 is 4-9 characters; 4 is typical
    text = build_interchange(
        isa13=isa13,
        gs06=gs06,
        transactions=[(st02, body)],
        transaction_set_id="837",
        functional_id="HC",                  # GS01 HC = health care claim
        implementation=writer_837.IMPLEMENTATION,
        sender_id=writer_837.SUBMITTER_ID,
        receiver_id=plan["payer_id"],
        created=created,
    )
    file_name = f"837P_{plan['plan_id']}_{created:%Y%m%d}_{isa13:09d}.x12"
    (config.outbound_dir / file_name).write_text(text)

    con.execute(
        "INSERT INTO submissions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [isa13, file_name, plan["plan_id"], isa13, gs06, st02, len(claims), created],
    )
    con.executemany(
        "INSERT INTO submission_claims VALUES (?, ?, ?, ?, ?, ?)",
        [
            [isa13, c.trip["trip_id"], c.frequency_code, c.payer_claim_number,
             len(lines := writer_837.service_lines(c.trip)),
             sum(charge for _, charge, _ in lines)]
            for c in claims
        ],
    )
    con.commit()
    return file_name


def run(config: Config, con: duckdb.DuckDBPyConnection) -> None:
    plans = {p["plan_id"]: p for p in rows_as_dicts(con, "SELECT * FROM plans")}
    members = {m["member_id"]: m for m in rows_as_dicts(con, "SELECT * FROM members")}
    vendors = {v["vendor_id"]: v for v in rows_as_dicts(con, "SELECT * FROM vendors")}

    files = []
    batches = groupby(pending_trips(con, config), key=lambda t: (t["reported_date"], t["plan_id"]))
    for (reported_date, plan_id), trips in batches:
        created = datetime.combine(reported_date + timedelta(days=1), NIGHTLY_RUN_TIME)
        claims = [ClaimInput(t, members[t["member_id"]], vendors[t["vendor_id"]]) for t in trips]
        for start in range(0, len(claims), config.max_claims_per_file):
            chunk = claims[start : start + config.max_claims_per_file]
            files.append(write_submission(con, config, plans[plan_id], chunk, created))
    print(f"build: wrote {len(files)} files")
