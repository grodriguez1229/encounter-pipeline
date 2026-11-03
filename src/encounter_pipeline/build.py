"""build: turn completed trips into outbound 837P files.

One call is one nightly run: every completed trip the vendor reported before tonight
that hasn't gone out yet is sent, batched by plan, at most max_claims_per_file per
file. run-all calls it once a night, so each trip goes out the night after it was
reported, with whatever fixes ops made up to then.
"""

from datetime import date, datetime, time
from itertools import groupby

import duckdb

from encounter_pipeline.config import Config
from encounter_pipeline.x12 import writer_837
from encounter_pipeline.x12.envelope import build_interchange, next_control_number
from encounter_pipeline.x12.writer_837 import ClaimInput

NIGHTLY_RUN_TIME = time(2, 0)


def night_of(day: date) -> datetime:
    """When the nightly run on this day happens."""
    return datetime.combine(day, NIGHTLY_RUN_TIME)


def rows_as_dicts(con: duckdb.DuckDBPyConnection, sql: str, params=None) -> list[dict]:
    cursor = con.execute(sql, params or [])
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def pending_trips(con: duckdb.DuckDBPyConnection, now: datetime) -> list[dict]:
    """Completed trips reported before tonight that were never submitted."""
    return rows_as_dicts(con, """
        SELECT t.*, m.plan_id
        FROM trips t
        JOIN members m USING (member_id)
        WHERE t.status = 'completed'
          AND t.reported_date < ?
          AND t.trip_id NOT IN (SELECT trip_id FROM submission_claims)
        ORDER BY m.plan_id, t.reported_date, t.vendor_id, t.member_id, t.trip_id
    """, [now.date()])


def write_submission(
    con: duckdb.DuckDBPyConnection,
    config: Config,
    plan: dict,
    claims: list[ClaimInput],
    created: datetime,
) -> str:
    """Write one 837 file and record it. Returns the file name."""
    con.begin()
    isa13 = next_control_number(con, "ISA")
    gs06 = next_control_number(con, "GS")
    st02 = f"{next_control_number(con, 'ST'):04d}"  # ST02 is 4-9 characters; 4 is typical
    # BHT03 comes back in the 277CA (TRN02 at the receiver level), so it has to identify
    # this one file. The ISA13 does.
    batch_id = f"{isa13:09d}"
    body = writer_837.transaction_body(claims, plan, batch_id, created)
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


def write_batches(con: duckdb.DuckDBPyConnection, config: Config,
                  claims_by_plan: dict[str, list[ClaimInput]], now: datetime) -> int:
    """Write each plan's claims as files of at most max_claims_per_file. Returns the count."""
    plans = {p["plan_id"]: p for p in rows_as_dicts(con, "SELECT * FROM plans")}
    files = 0
    for plan_id, claims in sorted(claims_by_plan.items()):
        for start in range(0, len(claims), config.max_claims_per_file):
            chunk = claims[start : start + config.max_claims_per_file]
            write_submission(con, config, plans[plan_id], chunk, now)
            files += 1
    return files


def run(config: Config, con: duckdb.DuckDBPyConnection, now: datetime | None = None) -> int:
    """Send tonight's new trips. Defaults to the run on run_date. Returns files written."""
    now = now or night_of(config.run_date)
    trips = pending_trips(con, now)
    if not trips:
        return 0
    members = {m["member_id"]: m for m in rows_as_dicts(con, "SELECT * FROM members")}
    vendors = {v["vendor_id"]: v for v in rows_as_dicts(con, "SELECT * FROM vendors")}
    claims_by_plan = {
        plan_id: [ClaimInput(t, members[t["member_id"]], vendors[t["vendor_id"]]) for t in group]
        for plan_id, group in groupby(trips, key=lambda t: t["plan_id"])
    }
    return write_batches(con, config, claims_by_plan, now)
