"""Read a 999 into one row per acknowledged transaction set.

AK1 names our functional group (GS06), each AK2 names one of our transaction sets
(ST02). Together they point at exactly one outbound 837 transaction.
"""

from dataclasses import dataclass, field
from datetime import datetime

from encounter_pipeline.x12.parser import parse


@dataclass
class Ack999:
    gs06: int                    # AK102: our group control number
    st02: str                    # AK202: our transaction set control number
    accepted: bool               # IK501 A (or E, accepted with errors)
    codes: list[str] = field(default_factory=list)    # IK502+: why it was rejected
    errors: list[str] = field(default_factory=list)   # IK3/IK4, as readable text


@dataclass
class File999:
    isa13: int
    created: datetime
    group_status: str            # AK901: A, P or R
    transactions: list[Ack999]


def read_999(text: str) -> File999:
    isa13, created, group_status = 0, datetime.min, ""
    gs06 = 0
    transactions: list[Ack999] = []
    current: Ack999 | None = None
    for seg in parse(text):
        match seg.id:
            case "ISA":
                isa13 = int(seg[13])
                created = datetime.strptime(seg[9] + seg[10], "%y%m%d%H%M")
            case "AK1":
                gs06 = int(seg[2])
            case "AK2":
                current = Ack999(gs06, seg[2], accepted=False)
                transactions.append(current)
            case "IK3":
                loop = f" in loop {seg[3]}" if seg[3] else ""
                current.errors.append(f"{seg[1]} segment {seg[2]}{loop}: error {seg[4]}")
            case "IK4":
                current.errors[-1] += f", element {seg[1]} (ref {seg[2]}) error {seg[3]}"
            case "IK5":
                current.accepted = seg[1] in ("A", "E")
                current.codes = [c for c in seg.elements[2:] if c]
            case "AK9":
                group_status = seg[1]
    return File999(isa13, created, group_status, transactions)
