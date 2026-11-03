"""trip: one trip's whole story, in time order.

Every file it went out in, the 999 and 277CA answers, what ops fixed in between, and
any final rejection. Reads the raw tables, plus the status code lookup model for
plain-English descriptions.
"""

import duckdb

from encounter_pipeline import report
from encounter_pipeline.config import Config

HEADER = """
    SELECT t.trip_id, t.trip_date, t.status, t.reported_date, t.level_of_service,
           t.loaded_miles, t.member_id, m.plan_id, t.vendor_id, v.vendor_name
    FROM trips t JOIN members m USING (member_id) JOIN vendors v USING (vendor_id)
    WHERE t.trip_id = $trip_id
"""

# One row per event: (when, what, detail). Vendor fixes show up on every trip from that
# vendor, since the NPI belongs to the vendor, not the trip.
TIMELINE = """
    WITH trip AS (SELECT trip_id, vendor_id FROM trips WHERE trip_id = $trip_id),
    sent AS (
        SELECT sc.submission_id, s.file_name, s.created_at, sc.frequency_code,
               sc.payer_claim_number
        FROM submission_claims sc JOIN submissions s USING (submission_id)
        WHERE sc.trip_id = $trip_id
    )
    SELECT created_at, 'sent',
           CASE frequency_code WHEN '1' THEN 'original (CLM05-3 = 1)'
               ELSE 'replacement (CLM05-3 = 7) of payer claim ' || payer_claim_number END
           || ' in ' || file_name
    FROM sent
    UNION ALL
    SELECT a.received_at, '999',
           CASE WHEN a.accepted THEN 'file accepted'
               ELSE 'file rejected: ' || coalesce(a.errors, a.codes) END
           || ' (' || a.response_file || ')'
    FROM submission_acks a JOIN sent USING (submission_id)
    UNION ALL
    SELECT h.received_at, '277CA',
           h.status || ' ' || h.status_codes
           || coalesce(' ' || c.description, '')
           || coalesce(', payer claim ' || h.payer_claim_number, '')
           || ' (' || h.response_file || ')'
    FROM claim_status_history h
    LEFT JOIN stg_status_codes c ON c.status_code = h.status_codes
    WHERE h.trip_id = $trip_id AND h.source = '277CA'
    UNION ALL
    SELECT a.adjusted_on::TIMESTAMP, 'fixed',
           a.table_name || '.' || a.field || ' ' || coalesce(a.old_value, '(missing)')
           || ' -> ' || a.new_value || ' after ' || a.reason
    FROM source_adjustments a, trip
    WHERE (a.table_name = 'trips' AND a.row_id = trip.trip_id)
       OR (a.table_name = 'vendors' AND a.row_id = trip.vendor_id)
    UNION ALL
    SELECT decided_at, 'final', reason || ' (' || status_codes || '), not resubmitting'
    FROM final_rejections WHERE trip_id = $trip_id
    ORDER BY 1, 2
"""


def run(config: Config, con: duckdb.DuckDBPyConnection, trip_id: str) -> None:
    row = con.execute(HEADER, {"trip_id": trip_id}).fetchone()
    if row is None:
        print(f"no trip {trip_id}")
        return
    (_, trip_date, status, reported, service, miles, member, plan, vendor, vendor_name) = row
    print(f"{trip_id}  {trip_date}  {status}, {service}, {miles} mi, reported {reported}")
    print(f"member {member} ({plan}), vendor {vendor} {vendor_name}")
    print()

    report.build(config, con)  # for the status code descriptions
    events = con.execute(TIMELINE, {"trip_id": trip_id}).fetchall()
    if not events:
        print("never submitted")
    for when, kind, detail in events:
        stamp = f"{when:%Y-%m-%d}" if f"{when:%H:%M}" == "00:00" else f"{when:%Y-%m-%d %H:%M}"
        print(f"{stamp:<16}  {kind:<5}  {detail}")
