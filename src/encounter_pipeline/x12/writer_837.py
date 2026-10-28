"""837P (professional claim, 005010X222A1) transaction body: everything between ST and SE.

The 837 is a tree, flattened into a list of segments. "Loops" are groups of
segments that repeat; the loop numbers come from the implementation guide:

    header      BHT
    1000A       submitter (us)
    1000B       receiver (the payer)
    2000A       billing provider  HL*n**20*1   one per vendor
      2010AA      vendor name, NPI, address, tax ID
      2000B       subscriber    HL*n*parent*22*0   one per member under that vendor
        2010BA      member name, ID, address, demographics
        2010BB      payer
        2300        claim (CLM)    one per trip
          2310E       pickup location
          2310F       dropoff location
          2400        service lines (LX + SV1 + DTP)

HL segments are what make the tree: HL01 is this node's ID, HL02 its parent's ID,
HL03 the level (20 = billing provider, 22 = subscriber), HL04 whether it has
children. Everything after an HL belongs to it until the next HL.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from encounter_pipeline.x12.segments import DEFAULT, Delimiters, segment

IMPLEMENTATION = "005010X222A1"

SUBMITTER_NAME = "SYNTHETIC NEMT BROKER"
SUBMITTER_ID = "SYNNEMT"

# Base code by level of service, plus S0215 per loaded mile. Fake fee schedule:
# encounters don't get paid per ride, but $0 lines get rejected by some payers.
BASE_CODES = {
    "ambulatory": ("A0100", Decimal("25.00")),   # non-emergency transport, taxi
    "wheelchair": ("A0130", Decimal("40.00")),   # non-emergency transport, wheelchair van
    "stretcher": ("T2005", Decimal("95.00")),    # non-emergency transport, stretcher van
}
MILEAGE_CODE = "S0215"
MILEAGE_RATE = Decimal("2.50")

# Claim filing indicator (SBR09): MC = Medicaid, 16 = HMO Medicare risk (Medicare Advantage).
FILING_INDICATOR = {"MEDICAID": "MC", "MA": "16"}

# Place of service 99 (other). NEMT isn't ambulance (41), and payers vary on this.
PLACE_OF_SERVICE = "99"


@dataclass
class ClaimInput:
    trip: dict
    member: dict
    vendor: dict
    frequency_code: str = "1"              # CLM05-3: 1 original, 7 replacement, 8 void
    payer_claim_number: str | None = None  # needed for 7 and 8


def amount(value: Decimal) -> str:
    """X12 decimal: no trailing zeros, no thousands separators. 25.00 -> 25, 52.50 -> 52.5"""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def diagnosis(trip: dict) -> str:
    """ICD-10 code without the dot, which is how the 837 carries them."""
    if trip["destination_type"] == "J" or trip["origin_type"] == "J":
        return "Z992"     # dependence on renal dialysis
    if trip["level_of_service"] == "wheelchair":
        return "Z993"     # dependence on wheelchair
    if trip["level_of_service"] == "stretcher":
        return "Z7401"    # bed confinement status
    return "Z0000"        # general adult exam, a stand-in for a routine visit


def service_lines(trip: dict) -> list[tuple[str, Decimal, Decimal]]:
    """(HCPCS, charge, units) for the base rate and the mileage."""
    code, rate = BASE_CODES[trip["level_of_service"]]
    miles = Decimal(trip["loaded_miles"])
    return [(code, rate, Decimal(1)), (MILEAGE_CODE, MILEAGE_RATE * miles, miles)]


def address_segments(prefix: str, row: dict, d: Delimiters) -> list[str]:
    return [
        segment("N3", row[f"{prefix}address1"].upper(), delims=d),
        segment("N4", row[f"{prefix}city"].upper(), row[f"{prefix}state"], row[f"{prefix}zip"],
                delims=d),
    ]


def claim_segments(c: ClaimInput, d: Delimiters) -> list[str]:
    trip = c.trip
    lines = service_lines(trip)
    total = sum(charge for _, charge, _ in lines)
    modifier = trip["origin_type"] + trip["destination_type"]
    service_date = trip["trip_date"].strftime("%Y%m%d")

    segs = [
        # 2300 claim. CLM01 is our ID for the claim (the trip), and it's what the 277CA
        # sends back so we can match responses. CLM05 is a composite:
        # place of service : B (meaning "professional place of service code") : frequency.
        segment("CLM", trip["trip_id"], amount(total), None, None,
                (PLACE_OF_SERVICE, "B", c.frequency_code),
                "Y", "A", "Y", "Y", delims=d),
    ]
    if c.payer_claim_number:
        # Replacement or void: which payer claim we're replacing.
        segs.append(segment("REF", "F8", c.payer_claim_number, delims=d))
    segs += [
        segment("HI", ("ABK", diagnosis(trip)), delims=d),  # ABK = principal diagnosis, ICD-10
        # 2310E pickup and 2310F dropoff. These loops are written for ambulance claims;
        # NEMT payers use them for the same thing.
        segment("NM1", "PW", "2", delims=d),
        *address_segments("pickup_", trip, d),
        segment("NM1", "45", "2", delims=d),
        *address_segments("dropoff_", trip, d),
    ]
    for n, (code, charge, units) in enumerate(lines, start=1):
        segs += [
            segment("LX", str(n), delims=d),
            # SV101 composite: HC = HCPCS, the code, then the origin/destination modifier.
            # SV103 UN = units. SV107 points at the first HI diagnosis.
            segment("SV1", ("HC", code, modifier), amount(charge), "UN", amount(units),
                    None, None, "1", delims=d),
            segment("DTP", "472", "D8", service_date, delims=d),  # 472 = date of service
        ]
    return segs


def transaction_body(
    claims: list[ClaimInput],
    plan: dict,
    batch_id: str,
    created: datetime,
    d: Delimiters = DEFAULT,
) -> list[str]:
    """Segments between ST and SE for one 837P covering one plan."""
    segs = [
        # BHT01 0019 = information source/receiver/provider/subscriber hierarchy.
        # BHT02 00 = original transmission. BHT06 RP = reporting: this is an encounter,
        # not a claim asking to be paid (that would be CH).
        segment("BHT", "0019", "00", batch_id, created.strftime("%Y%m%d"),
                created.strftime("%H%M"), "RP", delims=d),
        # 1000A submitter. 41 = submitter, 2 = organization, 46 = ETIN (ID the payer gave us).
        segment("NM1", "41", "2", SUBMITTER_NAME, None, None, None, None, "46", SUBMITTER_ID,
                delims=d),
        segment("PER", "IC", "ENCOUNTER OPS", "TE", "5555550100", delims=d),
        # 1000B receiver. 40 = receiver.
        segment("NM1", "40", "2", plan["plan_name"].upper(), None, None, None, None, "46",
                plan["payer_id"], delims=d),
    ]

    by_vendor: dict[str, list[ClaimInput]] = defaultdict(list)
    for c in claims:
        by_vendor[c.vendor["vendor_id"]].append(c)

    hl = 0
    for vendor_claims in by_vendor.values():
        v = vendor_claims[0].vendor
        hl += 1
        provider_hl = hl
        segs += [
            segment("HL", str(provider_hl), None, "20", "1", delims=d),
            # 2010AA. 85 = billing provider, XX = NPI. A missing NPI leaves NM108 without
            # NM109, which the payer's 999 check will catch.
            segment("NM1", "85", "2", v["vendor_name"].upper(), None, None, None, None,
                    "XX", v["npi"], delims=d),
            *address_segments("", v, d),
            segment("REF", "EI", v["tax_id"], delims=d),  # EI = employer ID (tax ID)
        ]

        by_member: dict[str, list[ClaimInput]] = defaultdict(list)
        for c in vendor_claims:
            by_member[c.member["member_id"]].append(c)

        for member_claims in by_member.values():
            m = member_claims[0].member
            hl += 1
            segs += [
                # HL04 0: no patient level below, because the patient is the subscriber.
                segment("HL", str(hl), str(provider_hl), "22", "0", delims=d),
                # SBR01 P = primary payer, SBR02 18 = patient is the subscriber (self).
                segment("SBR", "P", "18", None, None, None, None, None, None,
                        FILING_INDICATOR[plan["line_of_business"]], delims=d),
                # 2010BA. IL = insured, 1 = person, MI = member ID.
                segment("NM1", "IL", "1", m["last_name"].upper(), m["first_name"].upper(),
                        None, None, None, "MI", m["member_id"], delims=d),
                *address_segments("", m, d),
                segment("DMG", "D8", m["birth_date"].strftime("%Y%m%d"), m["gender"], delims=d),
                # 2010BB. PR = payer, PI = payer ID.
                segment("NM1", "PR", "2", plan["plan_name"].upper(), None, None, None, None,
                        "PI", plan["payer_id"], delims=d),
            ]
            for c in member_claims:
                segs += claim_segments(c, d)
    return segs
