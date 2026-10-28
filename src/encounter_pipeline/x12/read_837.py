"""Read claims back out of an 837P.

Walks the segments in order, keeping track of which loop we're in. The 837 doesn't
mark where a loop ends, so context comes from the last "loop opener" seen: an HL,
an NM1 with a given entity code, a CLM or an LX.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from encounter_pipeline.x12.parser import Segment, parse


@dataclass
class Line837:
    code: str
    modifier: str
    charge: Decimal
    units: Decimal
    service_date: date | None = None


@dataclass
class Claim837:
    trip_id: str
    charge: Decimal
    frequency_code: str
    billing_npi: str | None
    member_id: str
    payer_id: str
    payer_claim_number: str | None = None
    diagnosis: str | None = None
    pickup_zip: str | None = None
    dropoff_zip: str | None = None
    lines: list[Line837] = field(default_factory=list)


@dataclass
class File837:
    isa13: int
    gs06: int
    st02: str
    claims: list[Claim837]


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def read_837(text: str) -> File837:
    return claims_from_segments(parse(text))


def claims_from_segments(segments: list[Segment]) -> File837:
    isa13 = gs06 = 0
    st02 = ""
    claims: list[Claim837] = []
    billing_npi = member_id = payer_id = None
    entity = None             # entity code of the last NM1: 85, IL, PR, PW, 45...
    claim: Claim837 | None = None

    for seg in segments:
        match seg.id:
            case "ISA":
                isa13 = int(seg[13])
            case "GS":
                gs06 = int(seg[6])
            case "ST":
                st02 = seg[2]
            case "HL":
                claim = None  # a new HL closes any open claim
            case "NM1":
                entity = seg[1]
                if entity == "85":
                    billing_npi = seg[9] or None
                elif entity == "IL":
                    member_id = seg[9]
                elif entity == "PR":
                    payer_id = seg[9]
            case "CLM":
                claim = Claim837(
                    trip_id=seg[1],
                    charge=Decimal(seg[2]),
                    frequency_code=seg.composite(5)[2],
                    billing_npi=billing_npi,
                    member_id=member_id,
                    payer_id=payer_id,
                )
                claims.append(claim)
                entity = None
            case "REF" if claim and seg[1] == "F8":
                claim.payer_claim_number = seg[2]
            case "HI" if claim:
                claim.diagnosis = seg.composite(1)[1]
            case "N4" if claim and entity == "PW":
                claim.pickup_zip = seg[3]
            case "N4" if claim and entity == "45":
                claim.dropoff_zip = seg[3]
            case "SV1" if claim:
                qualifier, code, *modifiers = seg.composite(1)
                claim.lines.append(Line837(
                    code=code,
                    modifier=modifiers[0] if modifiers else "",
                    charge=Decimal(seg[2]),
                    units=Decimal(seg[4]),
                ))
            case "DTP" if claim and claim.lines and seg[1] == "472":
                claim.lines[-1].service_date = parse_date(seg[3])
    return File837(isa13, gs06, st02, claims)
