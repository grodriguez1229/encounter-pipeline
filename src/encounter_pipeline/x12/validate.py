"""Structural checks a receiver runs before looking at any claim, and the 999 results.

These are syntax checks, not business rules: do the trailers count right, do the
control numbers match, are paired elements present together. They work on any
transaction. Failures are reported in a 999; business problems (member not
eligible, bad NPI check digit) wait for the 277CA.
"""

from dataclasses import dataclass, field

from encounter_pipeline.x12.parser import Segment

# 837P loop IDs by NM101 entity code, so a 999 can say where the bad segment was.
NM1_LOOPS = {"41": "1000A", "40": "1000B", "85": "2010AA", "IL": "2010BA", "PR": "2010BB",
             "PW": "2310E", "45": "2310F"}


@dataclass
class ElementError:
    position: int        # IK401: element position in the segment (9 for NM109)
    element_ref: str     # IK402: data element reference number from the X12 dictionary
    code: str            # IK403: 2 = conditional required data element missing


@dataclass
class SegmentError:
    segment_id: str      # IK301
    position: int        # IK302: segment's position in the transaction, ST = 1
    loop_id: str         # IK303
    code: str            # IK304: 8 = segment has data element errors
    elements: list[ElementError] = field(default_factory=list)


@dataclass
class TransactionAck:
    transaction_set_id: str
    st02: str
    implementation: str
    segment_errors: list[SegmentError] = field(default_factory=list)
    # IK502+: 3 = ST02/SE02 don't match, 4 = SE01 count is wrong, 5 = segments have errors
    codes: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.codes


@dataclass
class GroupAck:
    functional_id: str
    gs06: str
    implementation: str
    declared_count: int                                       # GE01
    transactions: list[TransactionAck] = field(default_factory=list)
    # AK905+: 4 = GS06/GE02 don't match, 5 = GE01 count is wrong
    codes: list[str] = field(default_factory=list)

    @property
    def accepted_count(self) -> int:
        return sum(t.accepted for t in self.transactions)

    @property
    def status(self) -> str:
        """AK901: A accepted, P partially accepted, R rejected."""
        if self.codes or self.accepted_count == 0:
            return "R"
        if self.accepted_count < len(self.transactions):
            return "P"
        return "A"


def check_paired_ids(seg: Segment, position: int) -> SegmentError | None:
    """NM108 (ID qualifier) and NM109 (ID) must be both present or both absent.
    This is the "P0809" paired-element rule from the X12 dictionary."""
    if seg.id != "NM1" or bool(seg[8]) == bool(seg[9]):
        return None
    missing, ref = (9, "67") if seg[8] else (8, "66")
    return SegmentError("NM1", position, NM1_LOOPS.get(seg[1], ""), "8",
                        [ElementError(missing, ref, "2")])


def check_transaction(segs: list[Segment]) -> TransactionAck:
    """segs runs from ST through SE."""
    st, se = segs[0], segs[-1]
    ack = TransactionAck(st[1], st[2], st[3])
    for position, seg in enumerate(segs, start=1):
        if error := check_paired_ids(seg, position):
            ack.segment_errors.append(error)
    if ack.segment_errors:
        ack.codes.append("5")
    if se[2] != st[2]:
        ack.codes.append("3")
    if se[1] != str(len(segs)):
        ack.codes.append("4")
    return ack


def check_groups(segments: list[Segment]) -> list[GroupAck]:
    """Split the interchange into groups and transactions and check each one."""
    groups: list[GroupAck] = []
    group: GroupAck | None = None
    transaction: list[Segment] = []
    for seg in segments:
        match seg.id:
            case "GS":
                group = GroupAck(seg[1], seg[6], seg[8], declared_count=0)
            case "ST":
                transaction = [seg]
            case "SE":
                transaction.append(seg)
                group.transactions.append(check_transaction(transaction))
                transaction = []
            case "GE":
                group.declared_count = int(seg[1])
                if seg[2] != group.gs06:
                    group.codes.append("4")
                if group.declared_count != len(group.transactions):
                    group.codes.append("5")
                groups.append(group)
            case _ if transaction:
                transaction.append(seg)
    return groups
