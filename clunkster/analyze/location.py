"""Source navigation utils."""

import bisect
from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """Source location pointer."""

    asset_name: str
    file_name: str
    loc_line: int
    loc_column: int
    loc_index: int


class SourceLineMap:
    """LUT to convert absolute str indices into line/column."""

    __slots__ = ('_line_starts',)

    def __init__(self, line_starts: list[int]) -> None:
        """Initialize with raw line start offsets.

        Prefer using ``SourceLineMap.from_text(text)`` for parsing source code.
        :param line_starts: The raw line offsets.
        """
        self._line_starts = line_starts

    @classmethod
    def from_text(cls, text: str) -> Self:
        """Construct a ``SourceLineMap`` by parsing a GML source string.

        :param text: GML source.
        :return: Constructed ``SourceLineMap`` from parsed contents.
        """
        starts = [0]

        offset = 0
        while True:
            offset = text.find('\n', offset)
            if offset == -1:
                break
            offset += 1
            starts.append(offset)

        return cls(starts)

    def get_line_col(self, abs_index: int) -> tuple[int, int]:
        """Converts absolute string index into 1-based (line, column) tuple.

        :param abs_index: The absolute string index.
        :return: (line_number, column_number), both 1-based.
        """
        line_idx = bisect.bisect_right(self._line_starts, abs_index) - 1
        line_start_index = self._line_starts[line_idx]
        return line_idx + 1, (abs_index - line_start_index) + 1
