from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from encounter_pipeline.x12.read_277ca import ClaimAck, read_277ca
from encounter_pipeline.x12.read_999 import Ack999, read_999

FIXTURES = Path(__file__).parent / "fixtures"


def test_golden_999():
    f = read_999((FIXTURES / "golden_999.x12").read_text())
    assert (f.isa13, f.created, f.group_status) == (4320, datetime(2026, 3, 10, 9, 30), "P")
    assert f.transactions == [
        Ack999(55, "0055", accepted=True),
        Ack999(55, "0056", accepted=False, codes=["5"], errors=[
            "NM1 segment 14 in loop 2010AA: error 8, element 9 (ref 67) error 2",
            "N4 segment 17 in loop 2010BA: error 8, element 3 (ref 116) error 4",
        ]),
    ]


def test_golden_277ca():
    f = read_277ca((FIXTURES / "golden_277ca.x12").read_text())
    assert (f.isa13, f.batch_id) == (4321, "PLAN_MA120260308")
    assert (f.accepted_count, f.rejected_count) == (1, 2)
    assert f.claims == [
        ClaimAck("T00000101", ["A2:20"], "WQ", Decimal("106"), date(2026, 3, 10),
                 "2600000990001", date(2026, 3, 7)),
        ClaimAck("T00000102", ["A7:21", "A7:562:85"], "U", Decimal("72"), date(2026, 3, 10),
                 None, date(2026, 3, 7)),
        ClaimAck("T00000103", ["A3:109:IL"], "U", Decimal("72"), date(2026, 3, 10),
                 None, date(2026, 3, 8)),
    ]
    assert [c.status for c in f.claims] == ["accepted", "rejected", "rejected"]
