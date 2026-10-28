"""resubmit: work the rejections, then send what can be fixed.

Looks at each trip whose latest submission came back rejected and decides from the
rejection codes alone (never the answer key) what ops would do:

    999 rejection, claim fine     resend as is (it was rejected with the rest of the file)
    999 rejection, NPI missing    credentialing adds the NPI to the vendor, then resend
    A7:562:85 bad NPI             same vendor fix, then resend
    A7:500 bad ZIP                correct the address, then resend
    A7:187 bad date of service    correct the date, then resend
    A3:109 not eligible           final: the plan won't take it
    A3:54 duplicate               final: the payer already has this ride
    anything else                 final, flagged for a person to look at

Fixed claims go back as new originals (CLM05-3 = 1): a claim rejected on the 999 or
277CA never got into the payer's system, so there's nothing to replace.

Separately, a vendor's corrected mileage on an accepted encounter is sent as a
replacement (CLM05-3 = 7) with the payer's claim number in REF*F8.

Fixes happen 1-5 days after the rejection arrives and go out the next night. Anything
that would happen after run_date is left for later.
"""

import random
from collections import defaultdict
from datetime import date, datetime, timedelta

import duckdb

from encounter_pipeline.build import NIGHTLY_RUN_TIME, rows_as_dicts, write_submission
from encounter_pipeline.config import Config
from encounter_pipeline.generate import fake_npi
from encounter_pipeline.x12.writer_837 import ClaimInput

FINAL_REASONS = {
    "A3:109:IL": "member not eligible on the date of service",
    "A3:54": "duplicate of a claim the payer already accepted",
}

# 277CA rejections ops can fix: which field, on which table.
FIXES = {
    "A7:562:85": ("vendors", "npi"),
    "A7:500:PW": ("trips", "pickup_zip"),
    "A7:500:45": ("trips", "dropoff_zip"),
    "A7:187": ("trips", "trip_date"),
}

# Each trip's latest submission and the status that came back for it. Trips whose
# latest submission has no response yet drop out of the join.
LATEST_STATUS = """
    WITH latest AS (
        SELECT sc.trip_id, sc.submission_id
        FROM submission_claims sc JOIN submissions s USING (submission_id)
        QUALIFY row_number() OVER (
            PARTITION BY sc.trip_id ORDER BY s.created_at DESC, s.submission_id DESC) = 1
    ),
    latest_status AS (
        SELECT h.*, m.plan_id
        FROM latest
        JOIN claim_status_history h USING (trip_id, submission_id)
        JOIN trips t USING (trip_id)
        JOIN members m USING (member_id)
    )
"""


def next_night(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), NIGHTLY_RUN_TIME)


def log_adjustment(con, table: str, row_id: str, field: str, old, new, on: date,
                   reason: str) -> None:
    con.execute("INSERT INTO source_adjustments VALUES (?, ?, ?, ?, ?, ?, ?)",
                [table, row_id, field, str(old) if old is not None else None,
                 str(new), on, reason])


class Fixer:
    """Applies ops fixes to the source tables."""

    def __init__(self, config: Config, con: duckdb.DuckDBPyConnection):
        self.config, self.con = config, con

    def original_value(self, trip_id: str) -> str:
        # Stands in for ops calling the vendor to get the right value.
        return self.con.execute(
            "SELECT original_value FROM injected_problems WHERE trip_id = ?", [trip_id]
        ).fetchone()[0]

    def vendor_npi(self, trip_id: str, on: date, reason: str) -> None:
        vendor_id, npi = self.con.execute(
            "SELECT vendor_id, npi FROM trips JOIN vendors USING (vendor_id) WHERE trip_id = ?",
            [trip_id],
        ).fetchone()
        new_npi = fake_npi(random.Random(f"{self.config.seed}:npi:{vendor_id}"))
        if npi == new_npi:
            return  # already fixed for an earlier claim from this vendor
        self.con.execute("UPDATE vendors SET npi = ? WHERE vendor_id = ?", [new_npi, vendor_id])
        log_adjustment(self.con, "vendors", vendor_id, "npi", npi, new_npi, on, reason)

    def trip_field(self, trip_id: str, field: str, on: date, reason: str) -> None:
        old = self.con.execute(f"SELECT {field} FROM trips WHERE trip_id = ?",
                               [trip_id]).fetchone()[0]
        new = self.original_value(trip_id)
        self.con.execute(f"UPDATE trips SET {field} = ? WHERE trip_id = ?", [new, trip_id])
        log_adjustment(self.con, "trips", trip_id, field, old, new, on, reason)


def work_rejections(config: Config, con: duckdb.DuckDBPyConnection, batches: dict) -> None:
    """Fix or finalize each open rejection; fixed ones are added to batches."""
    fixer = Fixer(config, con)
    rejections = rows_as_dicts(con, LATEST_STATUS + """
        SELECT * FROM latest_status
        WHERE status = 'rejected'
          AND trip_id NOT IN (SELECT trip_id FROM final_rejections)
        ORDER BY received_at, trip_id
    """)
    for r in rejections:
        trip_id, codes = r["trip_id"], r["status_codes"]
        if r["source"] == "277CA" and codes not in FIXES:
            reason = FINAL_REASONS.get(codes, f"unhandled rejection {codes}, needs review")
            con.execute("INSERT INTO final_rejections VALUES (?, ?, ?, ?, ?)",
                        [trip_id, r["submission_id"], codes, reason, r["received_at"]])
            continue

        # A 999 bounces the whole file, and ops resends it together once it's fixed, so
        # every claim from that file gets the same delay. 277CA rejections are one-offs.
        if r["source"] == "999":
            rng = random.Random(f"{config.seed}:fix:{r['submission_id']}")
        else:
            rng = random.Random(f"{config.seed}:fix:{r['submission_id']}:{trip_id}")
        fixed_on = r["received_at"].date() + timedelta(days=rng.randint(1, 5))
        if fixed_on >= config.run_date:
            continue  # ops hasn't gotten to it yet

        if r["source"] == "999":
            # The 999 rejected the whole file. Only claims whose vendor has no NPI need a
            # fix; the rest were fine and just go again.
            npi = con.execute("SELECT npi FROM trips JOIN vendors USING (vendor_id) "
                              "WHERE trip_id = ?", [trip_id]).fetchone()[0]
            if npi is None:
                fixer.vendor_npi(trip_id, fixed_on, "999: billing provider NPI missing")
        else:
            table, field = FIXES[codes]
            if table == "vendors":
                fixer.vendor_npi(trip_id, fixed_on, f"277CA {codes}")
            else:
                fixer.trip_field(trip_id, field, fixed_on, f"277CA {codes}")
        batches[(next_night(fixed_on), r["plan_id"])].append((trip_id, "1", None))


def queue_replacements(config: Config, con: duckdb.DuckDBPyConnection, batches: dict) -> None:
    """Accepted encounters with a vendor mileage correction go out as replacements."""
    corrections = rows_as_dicts(con, LATEST_STATUS + """
        SELECT s.trip_id, s.plan_id, s.payer_claim_number, s.received_at,
               c.corrected_miles, c.reported_date, t.loaded_miles
        FROM latest_status s
        JOIN mileage_corrections c USING (trip_id)
        JOIN trips t USING (trip_id)
        WHERE s.status = 'accepted'
          AND t.loaded_miles <> c.corrected_miles
    """)
    for r in corrections:
        # Can't replace before the payer accepted it and gave us a claim number.
        sent_on = max(r["reported_date"], r["received_at"].date())
        if sent_on >= config.run_date:
            continue
        con.execute("UPDATE trips SET loaded_miles = ? WHERE trip_id = ?",
                    [r["corrected_miles"], r["trip_id"]])
        log_adjustment(con, "trips", r["trip_id"], "loaded_miles", r["loaded_miles"],
                       r["corrected_miles"], sent_on, "vendor sent corrected mileage")
        batches[(next_night(sent_on), r["plan_id"])].append(
            (r["trip_id"], "7", r["payer_claim_number"]))


def run(config: Config, con: duckdb.DuckDBPyConnection) -> int:
    """Returns how many files were written, so run-all knows when to stop."""
    con.begin()
    batches: dict = defaultdict(list)   # (night, plan_id) -> [(trip_id, frequency, pcn)]
    work_rejections(config, con, batches)
    queue_replacements(config, con, batches)
    con.commit()

    plans = {p["plan_id"]: p for p in rows_as_dicts(con, "SELECT * FROM plans")}
    members = {m["member_id"]: m for m in rows_as_dicts(con, "SELECT * FROM members")}
    vendors = {v["vendor_id"]: v for v in rows_as_dicts(con, "SELECT * FROM vendors")}
    trips = {t["trip_id"]: t for t in rows_as_dicts(con, "SELECT * FROM trips")}

    files = 0
    for (night, plan_id), items in sorted(batches.items()):
        claims = [
            ClaimInput(trips[trip_id], members[trips[trip_id]["member_id"]],
                       vendors[trips[trip_id]["vendor_id"]], freq, pcn)
            for trip_id, freq, pcn in items
        ]
        for start in range(0, len(claims), config.max_claims_per_file):
            write_submission(con, config, plans[plan_id],
                             claims[start : start + config.max_claims_per_file], night)
            files += 1
    finals = con.execute("SELECT count(*) FROM final_rejections").fetchone()[0]
    print(f"resubmit: wrote {files} files, {finals} final rejections so far")
    return files
