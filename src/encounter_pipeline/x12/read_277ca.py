"""Read a 277CA into one row per claim.

The claim is identified by TRN02 at the patient level (HL03 = PT), which is the
CLM01 we sent. Its verdict is in STC01, with up to two more status composites in
STC10 and STC11 (payers often send "A7:21" = invalid info, then "A7:562:85" to
say which info).
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from encounter_pipeline.x12.parser import parse

REJECTED_CATEGORIES = {"A3", "A6", "A7", "A8"}


@dataclass
class ClaimAck:
    trip_id: str
    status_codes: list[str] = field(default_factory=list)   # e.g. ["A7:21", "A7:562:85"]
    action: str = ""             # STC03: WQ accepted, U rejected
    charge: Decimal | None = None
    status_date: date | None = None
    payer_claim_number: str | None = None
    service_date: date | None = None

    @property
    def status(self) -> str:
        categories = {code.split(":")[0] for code in self.status_codes}
        if categories & REJECTED_CATEGORIES:
            return "rejected"
        if "A2" in categories:
            return "accepted"
        return "pending"         # only A1 (received), no verdict yet


@dataclass
class File277CA:
    isa13: int
    created: datetime
    batch_id: str                # TRN02 at the receiver level: our 837 BHT03
    accepted_count: int | None = None
    rejected_count: int | None = None
    claims: list[ClaimAck] = field(default_factory=list)


def parse_d8(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def read_277ca(text: str) -> File277CA:
    file = File277CA(0, datetime.min, "")
    level = ""                   # HL03 of the current HL: 20, 21, 19 or PT
    claim: ClaimAck | None = None
    for seg in parse(text):
        match seg.id:
            case "ISA":
                file.isa13 = int(seg[13])
                file.created = datetime.strptime(seg[9] + seg[10], "%y%m%d%H%M")
            case "HL":
                level = seg[3]
                claim = None
            case "TRN" if seg[1] == "2" and level == "21":
                file.batch_id = seg[2]
            case "TRN" if seg[1] == "2" and level == "PT":
                claim = ClaimAck(seg[2])
                file.claims.append(claim)
            case "QTY" if level == "21":
                if seg[1] == "90":
                    file.accepted_count = int(seg[2])
                elif seg[1] == "AA":
                    file.rejected_count = int(seg[2])
            case "STC" if claim:
                for i in (1, 10, 11):
                    if seg[i]:
                        # Rejoin with ":" so codes read the same whatever separator was sent.
                        claim.status_codes.append(":".join(seg.composite(i)))
                claim.status_date = parse_d8(seg[2])
                claim.action = seg[3]
                claim.charge = Decimal(seg[4]) if seg[4] else None
            case "REF" if claim and seg[1] == "1K":
                claim.payer_claim_number = seg[2]
            case "DTP" if claim and seg[1] == "472":
                # D8 is one date; RD8 is a range "start-end", keep the start.
                claim.service_date = parse_d8(seg[3].split("-")[0])
    return file
