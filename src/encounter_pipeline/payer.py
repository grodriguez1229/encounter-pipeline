"""simulate: a fake payer that answers our 837s with 999s and 277CAs.

This stands in for the clearinghouse and payer, so it only uses what they'd have:
the 837 files themselves and the plan's enrollment roster (our members table).
It doesn't read the answer key; every rejection comes from a check on the data.

It's stateless: every run replays all outbound files in the order they were sent,
with a random generator seeded per file, so the same files always get the same
responses. A response only gets written once its arrival time is on or before
run_date; later ones haven't "arrived" yet.
"""

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import duckdb

from encounter_pipeline.config import Config
from encounter_pipeline.npi import is_valid_npi
from encounter_pipeline.x12 import writer_277ca, writer_999
from encounter_pipeline.x12.envelope import build_interchange
from encounter_pipeline.x12.parser import parse
from encounter_pipeline.x12.read_837 import Claim837, File837, claims_from_segments
from encounter_pipeline.x12.validate import check_groups
from encounter_pipeline.x12.writer_277ca import ClaimStatus
from encounter_pipeline.x12.writer_837 import SUBMITTER_ID

Roster = dict[str, tuple[date, date | None]]

# The payer's own interchange numbers, kept apart from ours by range.
ISA_OFFSET_999 = 100_000_000
ISA_OFFSET_277CA = 200_000_000


def valid_zip(value: str | None) -> bool:
    return bool(value) and value.isdigit() and len(value) in (5, 9)


def eligible(roster: Roster, member_id: str, on: date) -> bool:
    start, end = roster[member_id]
    return start <= on and (end is None or on <= end)


def claim_key(c: Claim837) -> tuple:
    """What makes two claims the same ride: member, date, codes and modifiers."""
    return (c.member_id, c.lines[0].service_date,
            tuple((line.code, line.modifier) for line in c.lines))


def adjudicate(file: File837, roster: Roster, accepted_keys: set,
               received: date) -> list[ClaimStatus]:
    """Front-end edits, one verdict per claim. The first failing check wins.

    accepted_keys holds every claim this payer has accepted so far and is updated
    as claims are accepted, so a duplicate is caught whether it came in an earlier
    file or earlier in this one.
    """
    statuses = []
    for n, c in enumerate(file.claims, start=1):
        service_date = c.lines[0].service_date
        if service_date > received:
            status = ClaimStatus(c, "A7", "187")                  # date(s) of service
        elif not is_valid_npi(c.billing_npi):
            status = ClaimStatus(c, "A7", "562", "85")            # billing provider NPI
        elif not valid_zip(c.pickup_zip):
            status = ClaimStatus(c, "A7", "500", "PW")            # pickup ZIP
        elif not valid_zip(c.dropoff_zip):
            status = ClaimStatus(c, "A7", "500", "45")            # dropoff ZIP
        elif c.member_id not in roster:
            status = ClaimStatus(c, "A3", "33")                   # subscriber not found
        elif not eligible(roster, c.member_id, service_date):
            status = ClaimStatus(c, "A3", "109", "IL")            # subscriber not eligible
        elif c.frequency_code == "1" and claim_key(c) in accepted_keys:
            status = ClaimStatus(c, "A3", "54")                   # duplicate
        else:
            # Payer claim number: made from the interchange and position, so it's stable.
            status = ClaimStatus(c, "A2", "20", payer_claim_number=f"26{file.isa13:07d}{n:04d}")
            accepted_keys.add(claim_key(c))
        statuses.append(status)
    return statuses


@dataclass
class Response:
    kind: str              # 999 or 277CA
    arrives: datetime
    file_name: str
    text: str


def respond(config: Config, text: str, roster: Roster, accepted_keys: set) -> list[Response]:
    """The 999, and the 277CA if the 999 accepted the file, for one outbound 837."""
    segments = parse(text)
    file = claims_from_segments(segments)
    [group] = check_groups(segments)       # build writes one GS per file
    payer_id = segments[0][8].strip()      # ISA08: who we sent it to
    rng = random.Random(f"{config.seed}:{file.isa13}")

    def envelope(isa13: int, functional_id: str, set_id: str, implementation: str,
                 body: list[str], created: datetime) -> str:
        return build_interchange(
            isa13=isa13, gs06=isa13, transactions=[("0001", body)],
            transaction_set_id=set_id, functional_id=functional_id,
            implementation=implementation, sender_id=payer_id, receiver_id=SUBMITTER_ID,
            created=created,
        )

    # 999s are automatic and come back within a few hours.
    ack_time = file.created + timedelta(minutes=rng.randint(30, 240))
    responses = [Response(
        "999", ack_time,
        f"999_{payer_id}_{ack_time:%Y%m%d%H%M}_{ISA_OFFSET_999 + file.isa13:09d}.x12",
        # GS01 FA = functional acknowledgment
        envelope(ISA_OFFSET_999 + file.isa13, "FA", "999", writer_999.IMPLEMENTATION,
                 writer_999.transaction_body(group), ack_time),
    )]
    if group.status != "A":
        return responses   # rejected at the 999: no claim ever reaches the payer's system

    # 277CAs take longer, and a few are days late.
    roll = rng.random()
    if roll < 0.55:
        lag_days = 0
    elif roll < 0.75:
        lag_days = 1
    elif roll < 0.85:
        lag_days = 2
    elif roll < 0.95:
        lag_days = rng.randint(3, 6)
    else:
        lag_days = rng.randint(7, 14)
    claim_ack_time = ack_time + timedelta(days=lag_days, hours=rng.randint(1, 8))
    statuses = adjudicate(file, roster, accepted_keys, file.created.date())
    body = writer_277ca.transaction_body(file, payer_id, statuses, file.created, claim_ack_time)
    responses.append(Response(
        "277CA", claim_ack_time,
        f"277CA_{payer_id}_{claim_ack_time:%Y%m%d%H%M}_{ISA_OFFSET_277CA + file.isa13:09d}.x12",
        # GS01 HN = health care claim status notification
        envelope(ISA_OFFSET_277CA + file.isa13, "HN", "277", writer_277ca.IMPLEMENTATION,
                 body, claim_ack_time),
    ))
    return responses


def send_order(text: str) -> tuple[str, str, str]:
    """ISA09 date, ISA10 time, ISA13 control number."""
    isa = parse(text)[0]
    return (isa[9], isa[10], isa[13])


def outbound_in_send_order(outbound_dir: Path) -> list[str]:
    return sorted((p.read_text() for p in outbound_dir.glob("*.x12")), key=send_order)


def run(config: Config, con: duckdb.DuckDBPyConnection) -> None:
    roster = {
        member_id: (start, end)
        for member_id, start, end in con.execute(
            "SELECT member_id, eligibility_start, eligibility_end FROM members"
        ).fetchall()
    }
    cutoff = datetime.combine(config.run_date + timedelta(days=1), time())
    accepted_keys: set = set()
    written = 0
    for text in outbound_in_send_order(config.outbound_dir):
        for r in respond(config, text, roster, accepted_keys):
            path = config.inbound_dir / r.file_name
            if r.arrives < cutoff and not path.exists():
                path.write_text(r.text)
                written += 1
    print(f"simulate: wrote {written} response files")
