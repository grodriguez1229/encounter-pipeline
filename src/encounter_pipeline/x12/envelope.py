"""The three envelopes around every X12 transaction, and their control numbers.

    ISA ... IEA   interchange: one per file, who it's from and to
    GS  ... GE    functional group: transactions of one type (HC = 837 claims)
    ST  ... SE    transaction set: the actual 837 (or 999, 277CA)

Each header carries a control number and its trailer repeats it, along with a
count of what's inside. The control numbers are what responses point back to:
a 999 names the GS06 and ST02 it's acknowledging.
"""

from dataclasses import dataclass, field
from datetime import datetime

import duckdb

from encounter_pipeline.x12.segments import DEFAULT, Delimiters, isa_segment, segment


def next_control_number(con: duckdb.DuckDBPyConnection, kind: str) -> int:
    """Next number for ISA13, GS06 or ST02. Stored so they keep counting across runs;
    partners reject an interchange that reuses a control number."""
    row = con.execute(
        """
        INSERT INTO control_numbers VALUES (?, 1)
        ON CONFLICT (kind) DO UPDATE SET last_value = last_value + 1
        RETURNING last_value
        """,
        [kind],
    ).fetchone()
    return row[0]


@dataclass
class Interchange:
    text: str
    isa13: int
    gs06: int
    st02s: list[str] = field(default_factory=list)


def build_interchange(
    con: duckdb.DuckDBPyConnection,
    *,
    transactions: list[list[str]],
    transaction_set_id: str,     # ST01, e.g. 837
    functional_id: str,          # GS01, e.g. HC
    implementation: str,         # GS08 / ST03, e.g. 005010X222A1
    sender_id: str,
    receiver_id: str,
    created: datetime,
    usage: str = "T",
    delims: Delimiters = DEFAULT,
    newlines: bool = True,
) -> Interchange:
    """Wrap transaction bodies in ST/SE, one GS/GE and one ISA/IEA.

    Each item in `transactions` is the list of segments between ST and SE.
    `newlines` puts a line break after each terminator. It's only for readability;
    the parser ignores it.
    """
    isa13 = next_control_number(con, "ISA")
    gs06 = next_control_number(con, "GS")

    segments = [
        isa_segment(sender_id, receiver_id, isa13, created, usage, delims),
        segment(
            "GS",
            functional_id,
            sender_id,
            receiver_id,
            created.strftime("%Y%m%d"),    # GS04 is CCYYMMDD, unlike ISA09
            created.strftime("%H%M"),
            str(gs06),                     # GS06 group control number
            "X",                           # GS07 responsible agency: X12
            implementation,                # GS08 which implementation guide we follow
            delims=delims,
        ),
    ]
    st02s = []
    for body in transactions:
        st02 = f"{next_control_number(con, 'ST'):04d}"
        st02s.append(st02)
        st = segment("ST", transaction_set_id, st02, implementation, delims=delims)
        # SE01 counts every segment in the transaction, including ST and SE themselves.
        se = segment("SE", str(len(body) + 2), st02, delims=delims)
        segments += [st, *body, se]
    segments += [
        segment("GE", str(len(transactions)), str(gs06), delims=delims),  # GE01 = # of ST
        segment("IEA", "1", f"{isa13:09d}", delims=delims),               # IEA01 = # of GS
    ]

    terminator = delims.segment + ("\n" if newlines else "")
    return Interchange("".join(s + terminator for s in segments), isa13, gs06, st02s)
