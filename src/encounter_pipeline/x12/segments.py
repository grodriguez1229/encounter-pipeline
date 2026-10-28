"""Turning values into X12 segments.

An X12 file is a string of segments. Each segment is an ID followed by elements,
separated by the element separator and ended by the segment terminator:

    NM1*85*2*WATKINS TRANSPORT LLC*****XX*9435031361~

Some elements are composites made of sub-elements joined by the component
separator (CLM05 is `41:B:1`). Nothing about these characters is fixed by the
standard: the sender picks them and announces them in the ISA segment, which is
why the parser reads them from there instead of assuming `*` and `~`.
"""

from dataclasses import dataclass
from datetime import datetime

Element = str | tuple[str, ...] | None


@dataclass(frozen=True)
class Delimiters:
    element: str = "*"
    component: str = ":"     # sent in ISA16
    repetition: str = "^"    # sent in ISA11
    segment: str = "~"

    def all(self) -> tuple[str, ...]:
        return (self.element, self.component, self.repetition, self.segment)


DEFAULT = Delimiters()


def check_value(value: str, delims: Delimiters) -> str:
    """X12 has no escape character, so a delimiter inside a value would corrupt the file."""
    for d in delims.all():
        if d in value:
            raise ValueError(f"value {value!r} contains delimiter {d!r}")
    return value


def segment(seg_id: str, *elements: Element, delims: Delimiters = DEFAULT) -> str:
    """Build one segment, without the terminator.

    None means an empty element. A tuple is a composite. Trailing empty elements are
    dropped, because X12 doesn't allow a segment to end with empty delimiters.
    """
    values = []
    for el in elements:
        if el is None:
            values.append("")
        elif isinstance(el, tuple):
            parts = [check_value(p or "", delims) for p in el]
            while parts and parts[-1] == "":
                parts.pop()
            values.append(delims.component.join(parts))
        else:
            values.append(check_value(el, delims))
    while values and values[-1] == "":
        values.pop()
    return delims.element.join([seg_id, *values])


def isa_segment(
    sender_id: str,
    receiver_id: str,
    control_number: int,
    created: datetime,
    usage: str = "T",
    delims: Delimiters = DEFAULT,
) -> str:
    """The interchange header. Unlike every other segment, every ISA element is fixed width,
    so the segment is always 106 characters including the terminator. That's what lets a
    parser find the delimiters before it knows what they are: the element separator is
    character 4, the component separator is character 105, the terminator is character 106.
    """
    if len(sender_id) > 15 or len(receiver_id) > 15:
        raise ValueError("ISA sender/receiver IDs are at most 15 characters")
    elements = [
        "00", " " * 10,             # ISA01-02 authorization info: none
        "00", " " * 10,             # ISA03-04 security info: none
        "ZZ", sender_id.ljust(15),  # ISA05-06 sender, ZZ = mutually defined ID
        "ZZ", receiver_id.ljust(15),  # ISA07-08 receiver
        created.strftime("%y%m%d"),  # ISA09 date, YYMMDD
        created.strftime("%H%M"),    # ISA10 time, HHMM
        delims.repetition,           # ISA11 repetition separator
        "00501",                     # ISA12 version of the ISA/IEA envelope
        f"{control_number:09d}",     # ISA13 interchange control number, always 9 digits
        "0",                         # ISA14 don't send a TA1 acknowledgment
        usage,                       # ISA15 T = test, P = production
        delims.component,            # ISA16 component separator
    ]
    return delims.element.join(["ISA", *elements])
