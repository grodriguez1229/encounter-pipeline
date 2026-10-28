from datetime import date, datetime
from decimal import Decimal

from encounter_pipeline.x12.writer_837 import ClaimInput, amount, transaction_body

PLAN = {"plan_id": "PLAN_MA1", "plan_name": "Synthetic Health Advantage",
        "line_of_business": "MA", "payer_id": "SYNMA1"}
ADDRESS = {"address1": "1 Main St", "city": "Austin", "state": "TX", "zip": "78701"}


def vendor(vendor_id="V0001", npi="9435031361"):
    return {"vendor_id": vendor_id, "vendor_name": "Test Transport LLC", "npi": npi,
            "tax_id": "001234567", **ADDRESS}


def member(member_id="M00000001"):
    return {"member_id": member_id, "first_name": "Ann", "last_name": "Lee",
            "birth_date": date(1950, 3, 4), "gender": "F", **ADDRESS}


def trip(trip_id="T00000001", los="wheelchair", miles="12.4"):
    return {"trip_id": trip_id, "trip_date": date(2026, 3, 2), "origin_type": "R",
            "destination_type": "P", "level_of_service": los, "loaded_miles": Decimal(miles),
            **{f"pickup_{k}": v for k, v in ADDRESS.items()},
            **{f"dropoff_{k}": v for k, v in ADDRESS.items()}}


def body(claims):
    return transaction_body(claims, PLAN, "B1", datetime(2026, 3, 5, 9, 0))


def test_amount_formatting():
    assert amount(Decimal("25.00")) == "25"
    assert amount(Decimal("31.00")) == "31"
    assert amount(Decimal("52.50")) == "52.5"
    assert amount(Decimal("0")) == "0"


def test_claim_and_lines():
    segs = body([ClaimInput(trip(), member(), vendor())])
    # 40 base + 12.4 miles * 2.50 = 71
    assert "CLM*T00000001*71***99:B:1*Y*A*Y*Y" in segs
    assert "HI*ABK:Z993" in segs
    assert "SV1*HC:A0130:RP*40*UN*1***1" in segs
    assert "SV1*HC:S0215:RP*31*UN*12.4***1" in segs
    assert segs.count("DTP*472*D8*20260302") == 2
    assert "BHT*0019*00*B1*20260305*0900*RP" == segs[0]
    assert "SBR*P*18*******16" in segs


def test_replacement_carries_payer_claim_number():
    segs = body([ClaimInput(trip(), member(), vendor(), "7", "PCN123")])
    clm = next(i for i, s in enumerate(segs) if s.startswith("CLM"))
    assert segs[clm].endswith("99:B:7*Y*A*Y*Y")
    assert segs[clm + 1] == "REF*F8*PCN123"


def test_missing_npi_leaves_qualifier_without_id():
    segs = body([ClaimInput(trip(), member(), vendor(npi=None))])
    assert "NM1*85*2*TEST TRANSPORT LLC*****XX" in segs


def test_hl_hierarchy_groups_by_vendor_then_member():
    claims = [
        ClaimInput(trip("T1"), member("M1"), vendor("V1")),
        ClaimInput(trip("T2"), member("M1"), vendor("V1")),
        ClaimInput(trip("T3"), member("M2"), vendor("V1")),
        ClaimInput(trip("T4"), member("M1"), vendor("V2")),
    ]
    hls = [s for s in body(claims) if s.startswith("HL")]
    assert hls == [
        "HL*1**20*1",
        "HL*2*1*22*0",   # M1 under V1, with T1 and T2
        "HL*3*1*22*0",   # M2 under V1
        "HL*4**20*1",
        "HL*5*4*22*0",   # M1 under V2
    ]
