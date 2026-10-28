from datetime import datetime

from encounter_pipeline.x12 import writer_999
from encounter_pipeline.x12.envelope import build_interchange
from encounter_pipeline.x12.parser import parse
from encounter_pipeline.x12.validate import check_groups


def interchange(*bodies: list[str]) -> str:
    return build_interchange(
        isa13=1, gs06=7,
        transactions=[(f"{i:04d}", body) for i, body in enumerate(bodies, start=1)],
        transaction_set_id="837", functional_id="HC", implementation="005010X222A1",
        sender_id="S", receiver_id="R", created=datetime(2026, 1, 2, 3, 4),
    )


GOOD = ["BHT*0019*00*B1*20260102*0304*RP", "NM1*85*2*ACME*****XX*9435031361"]
MISSING_NPI = ["BHT*0019*00*B1*20260102*0304*RP", "NM1*85*2*ACME*****XX"]


def ack_lines(text: str) -> list[str]:
    [group] = check_groups(parse(text))
    return writer_999.transaction_body(group)


def test_clean_group_is_accepted():
    assert ack_lines(interchange(GOOD)) == [
        "AK1*HC*7*005010X222A1",
        "AK2*837*0001*005010X222A1",
        "IK5*A",
        "AK9*A*1*1*1",
    ]


def test_missing_npi_rejects_the_transaction():
    assert ack_lines(interchange(MISSING_NPI)) == [
        "AK1*HC*7*005010X222A1",
        "AK2*837*0001*005010X222A1",
        "IK3*NM1*3*2010AA*8",    # third segment counting ST as 1
        "IK4*9*67*2",            # NM109 (element 67, identification code) missing
        "IK5*R*5",
        "AK9*R*1*1*0",
    ]


def test_one_bad_transaction_of_two_is_partial():
    lines = ack_lines(interchange(GOOD, MISSING_NPI))
    assert lines[-1] == "AK9*P*2*2*1"


def test_wrong_trailer_counts_and_control_numbers():
    text = interchange(GOOD).replace("SE*4*0001", "SE*5*0002").replace("GE*1*7", "GE*2*8")
    lines = ack_lines(text)
    assert "IK5*R*3*4" in lines
    assert lines[-1] == "AK9*R*2*1*0*4*5"
