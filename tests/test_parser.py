from datetime import datetime

import pytest

from encounter_pipeline.x12.parser import parse, read_delimiters
from encounter_pipeline.x12.segments import Delimiters, isa_segment, segment


def make_file(delims: Delimiters, newlines: bool) -> str:
    segs = [
        isa_segment("S", "R", 7, datetime(2026, 1, 2, 3, 4), delims=delims),
        segment("GS", "HC", "S", "R", "20260102", "0304", "7", "X", "005010X222A1",
                delims=delims),
        segment("CLM", "T1", "10", None, None, ("99", "B", "1"), delims=delims),
        segment("NM1", "85", "2", "ACME", None, None, None, None, "XX", delims=delims),
    ]
    end = delims.segment + ("\n" if newlines else "")
    return "".join(s + end for s in segs)


@pytest.mark.parametrize("delims", [
    Delimiters(),
    Delimiters(element="|", component=">", repetition="!", segment="\n"),
])
@pytest.mark.parametrize("newlines", [True, False])
def test_reads_delimiters_from_isa(delims, newlines):
    text = make_file(delims, newlines)
    assert read_delimiters(text) == delims
    segs = parse(text)
    assert [s.id for s in segs] == ["ISA", "GS", "CLM", "NM1"]
    assert segs[0][13] == "000000007"
    assert segs[2].composite(5) == ["99", "B", "1"]
    # NM109 was dropped as a trailing empty element; it reads back as "".
    assert segs[3][8] == "XX"
    assert segs[3][9] == ""


def test_rejects_non_x12():
    with pytest.raises(ValueError):
        parse("GS*HC~")
