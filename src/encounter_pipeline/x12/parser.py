"""Splitting an X12 file into segments and elements.

The delimiters are whatever the sender put in the ISA, so they're read from there.
Because the ISA is fixed width, their positions are known before parsing anything:
character 4 is the element separator, character 105 the component separator,
character 106 the segment terminator. The repetition separator is ISA11.
"""

from dataclasses import dataclass

from encounter_pipeline.x12.segments import Delimiters


@dataclass
class Segment:
    """One segment. Indexes match X12 numbering: seg[1] is NM101, seg[9] is NM109.
    Elements past the end read as "", since trailing empty elements get dropped."""

    elements: list[str]
    delims: Delimiters

    @property
    def id(self) -> str:
        return self.elements[0]

    def __getitem__(self, i: int) -> str:
        return self.elements[i] if i < len(self.elements) else ""

    def __len__(self) -> int:
        return len(self.elements)

    def composite(self, i: int) -> list[str]:
        """Sub-elements of a composite, e.g. CLM05 '99:B:1' -> ['99', 'B', '1']."""
        return self[i].split(self.delims.component)

    def __str__(self) -> str:
        return self.delims.element.join(self.elements)


def read_delimiters(text: str) -> Delimiters:
    if not text.startswith("ISA") or len(text) < 106:
        raise ValueError("not an X12 interchange: doesn't start with a full ISA segment")
    element = text[3]
    isa = text[:106].split(element)
    return Delimiters(element=element, component=text[104], repetition=isa[11],
                      segment=text[105])


def parse(text: str) -> list[Segment]:
    text = text.lstrip()
    delims = read_delimiters(text)
    segments = []
    for raw in text.split(delims.segment):
        # Line breaks between segments are common for readability; they aren't data.
        raw = raw.strip("\r\n")
        if raw:
            segments.append(Segment(raw.split(delims.element), delims))
    return segments
