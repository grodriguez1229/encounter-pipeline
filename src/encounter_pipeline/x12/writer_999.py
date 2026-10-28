"""999 implementation acknowledgment (005010X231A1) body.

One 999 answers one functional group: AK1 names the group (by GS06), then for each
transaction an AK2 (by ST02), any IK3/IK4 errors, and IK5 with the verdict. AK9
gives the verdict for the whole group.
"""

from encounter_pipeline.x12.segments import DEFAULT, Delimiters, segment
from encounter_pipeline.x12.validate import GroupAck

IMPLEMENTATION = "005010X231A1"


def transaction_body(group: GroupAck, d: Delimiters = DEFAULT) -> list[str]:
    segs = [segment("AK1", group.functional_id, group.gs06, group.implementation, delims=d)]
    for tx in group.transactions:
        segs.append(segment("AK2", tx.transaction_set_id, tx.st02, tx.implementation, delims=d))
        for err in tx.segment_errors:
            segs.append(segment("IK3", err.segment_id, str(err.position), err.loop_id or None,
                                err.code, delims=d))
            for el in err.elements:
                segs.append(segment("IK4", str(el.position), el.element_ref, el.code, delims=d))
        # IK501: A accepted, R rejected. IK502+ say why.
        segs.append(segment("IK5", "A" if tx.accepted else "R", *tx.codes, delims=d))
    segs.append(segment(
        "AK9",
        group.status,
        str(group.declared_count),       # AK902 transaction sets the GE said were there
        str(len(group.transactions)),    # AK903 transaction sets actually received
        str(group.accepted_count),       # AK904 transaction sets accepted
        *group.codes,
        delims=d,
    ))
    return segs
