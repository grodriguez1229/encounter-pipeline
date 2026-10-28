"""277CA claim acknowledgment (005010X214) body.

Where the 999 says "your file was readable", the 277CA says what happened to each
claim: accepted into the payer's system, or rejected and why. It's another HL tree:

    2000A  HL*1**20*1   information source (the payer)
    2000B  HL*2*1*21*1  information receiver (us), with a file-level STC and counts
    2000C  HL*n*2*19*1  billing provider
    2000D  HL*m*n*PT    patient, one per claim: TRN*2 echoes CLM01, STC is the verdict

STC01 is a composite: category : status code : entity. The category says what
happened (A2 accepted, A3/A7 rejected), the status code says about what (562 NPI,
109 not eligible), and the entity says whose (85 billing provider, IL subscriber).
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from itertools import groupby

from encounter_pipeline.x12.read_837 import Claim837, File837
from encounter_pipeline.x12.segments import DEFAULT, Delimiters, segment
from encounter_pipeline.x12.writer_837 import SUBMITTER_ID, SUBMITTER_NAME, amount

IMPLEMENTATION = "005010X214"


@dataclass
class ClaimStatus:
    claim: Claim837
    category: str                # A2 accepted, A3 / A7 rejected
    status_code: str             # 20 accepted, or what was wrong
    entity: str | None = None    # whose information was wrong
    payer_claim_number: str | None = None

    @property
    def accepted(self) -> bool:
        return self.category == "A2"


def d8(value: date | datetime) -> str:
    return value.strftime("%Y%m%d")


def transaction_body(
    file: File837,
    payer_id: str,
    statuses: list[ClaimStatus],
    received: datetime,
    processed: datetime,
    d: Delimiters = DEFAULT,
) -> list[str]:
    accepted = [s for s in statuses if s.accepted]
    rejected = [s for s in statuses if not s.accepted]
    segs = [
        # BHT01 0085 = source/receiver/provider/patient hierarchy, BHT02 08 = status,
        # BHT06 TH = receipt acknowledgment.
        segment("BHT", "0085", "08", f"{file.isa13:09d}", d8(processed),
                processed.strftime("%H%M"), "TH", delims=d),
        segment("HL", "1", None, "20", "1", delims=d),
        segment("NM1", "PR", "2", file.payer_name, None, None, None, None, "PI", payer_id,
                delims=d),
        segment("TRN", "1", f"{file.isa13:09d}", delims=d),
        segment("DTP", "050", "D8", d8(received), delims=d),    # 050 = received
        segment("DTP", "009", "D8", d8(processed), delims=d),   # 009 = processed
        segment("HL", "2", "1", "21", "1", delims=d),
        segment("NM1", "41", "2", SUBMITTER_NAME, None, None, None, None, "46", SUBMITTER_ID,
                delims=d),
        segment("TRN", "2", file.batch_id, delims=d),           # our BHT03, echoed back
        # A1:19:PR = the payer (PR) acknowledges receipt of the batch.
        segment("STC", ("A1", "19", "PR"), d8(processed), "WQ",
                amount(sum((s.claim.charge for s in statuses), Decimal(0))), delims=d),
        segment("QTY", "90", str(len(accepted)), delims=d),     # 90 = accepted count
        segment("QTY", "AA", str(len(rejected)), delims=d),     # AA = rejected count
        segment("AMT", "YU", amount(sum((s.claim.charge for s in accepted), Decimal(0))),
                delims=d),
        segment("AMT", "YY", amount(sum((s.claim.charge for s in rejected), Decimal(0))),
                delims=d),
    ]

    hl = 2
    by_provider = groupby(statuses, key=lambda s: (s.claim.billing_name, s.claim.billing_npi))
    for (name, npi), provider_statuses in by_provider:
        hl += 1
        provider_hl = hl
        segs += [
            segment("HL", str(provider_hl), "2", "19", "1", delims=d),
            segment("NM1", "85", "2", name, None, None, None, None, "XX" if npi else None, npi,
                    delims=d),
        ]
        for s in provider_statuses:
            c = s.claim
            hl += 1
            segs += [
                segment("HL", str(hl), str(provider_hl), "PT", delims=d),
                segment("NM1", "QC", "1", c.member_last_name, c.member_first_name, None, None,
                        None, "MI", c.member_id, delims=d),
                # The key for matching: TRN02 is the CLM01 we sent.
                segment("TRN", "2", c.trip_id, delims=d),
                # STC03 WQ = accepted, U = rejected.
                segment("STC", (s.category, s.status_code, s.entity), d8(processed),
                        "WQ" if s.accepted else "U", amount(c.charge), delims=d),
            ]
            if s.payer_claim_number:
                # 1K = payer's claim number. Needed later to send a replacement.
                segs.append(segment("REF", "1K", s.payer_claim_number, delims=d))
            segs.append(segment("DTP", "472", "D8", d8(c.lines[0].service_date), delims=d))
    return segs
