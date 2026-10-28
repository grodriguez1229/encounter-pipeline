from datetime import datetime

import pytest

from encounter_pipeline.config import Config
from encounter_pipeline.db import connect
from encounter_pipeline.x12.envelope import build_interchange, next_control_number
from encounter_pipeline.x12.segments import Delimiters, isa_segment, segment

CREATED = datetime(2026, 6, 30, 14, 5)


def test_segment_trims_trailing_empties_and_joins_composites():
    assert segment("CLM", "T1", "0", None, None, ("41", "B", "1")) == "CLM*T1*0***41:B:1"
    assert segment("NM1", "IL", "1", "DOE", None, None) == "NM1*IL*1*DOE"
    assert segment("SV1", ("HC", "A0100", None)) == "SV1*HC:A0100"


def test_segment_rejects_delimiters_in_values():
    with pytest.raises(ValueError):
        segment("NM1", "SMITH*JONES")
    with pytest.raises(ValueError):
        segment("N3", "APT 4~B")


def test_isa_is_fixed_width_and_carries_the_delimiters():
    delims = Delimiters(element="|", component=">", repetition="!", segment="\n")
    isa = isa_segment("SENDER", "RECEIVER", 42, CREATED, delims=delims) + delims.segment
    assert len(isa) == 106
    assert isa[3] == "|"
    assert isa[104] == ">"
    assert isa[105] == "\n"
    fields = isa.rstrip("\n").split("|")
    assert fields[6] == "SENDER".ljust(15)
    assert fields[11] == "!"
    assert fields[13] == "000000042"


def test_control_numbers_keep_counting_across_connections(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    with connect(config) as con:
        assert [next_control_number(con, "ISA") for _ in range(3)] == [1, 2, 3]
        assert next_control_number(con, "GS") == 1
    with connect(config) as con:
        assert next_control_number(con, "ISA") == 4


def split(text: str) -> list[list[str]]:
    return [s.split("*") for s in text.replace("\n", "").split("~") if s]


def test_envelope_counts_and_control_numbers_match(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    with connect(config) as con:
        bodies = [["BHT*0019*00*X"], ["BHT*0019*00*Y", "REF*X*1"]]
        ic = build_interchange(
            con, transactions=bodies, transaction_set_id="837", functional_id="HC",
            implementation="005010X222A1", sender_id="SENDER", receiver_id="RECEIVER",
            created=CREATED,
        )
    segs = split(ic.text)
    by_id = {}
    for s in segs:
        by_id.setdefault(s[0], []).append(s)

    isa, iea = by_id["ISA"][0], by_id["IEA"][0]
    gs, ge = by_id["GS"][0], by_id["GE"][0]
    assert isa[13] == iea[2] == f"{ic.isa13:09d}"
    assert iea[1] == "1"
    assert gs[6] == ge[2] == str(ic.gs06)
    assert ge[1] == "2"
    assert gs[4] == "20260630" and isa[9] == "260630"

    # SE01 = segments from ST through SE inclusive; SE02 = ST02.
    st_positions = [i for i, s in enumerate(segs) if s[0] == "ST"]
    se_positions = [i for i, s in enumerate(segs) if s[0] == "SE"]
    for st_i, se_i, st02 in zip(st_positions, se_positions, ic.st02s, strict=True):
        assert segs[st_i][2] == segs[se_i][2] == st02
        assert int(segs[se_i][1]) == se_i - st_i + 1
