"""Source line map."""

import bisect
import itertools as it
from typing import Self


class LineMap:
    """LUT to convert absolute str indices into line/column."""

    __slots__ = ('line_pref', 'line_starts')

    def __init__(self, line_starts: list[int]) -> None:
        """Initialize with raw line start offsets.

        Prefer using ``LineMap.from_text(text)`` for parsing source code.
        :param line_starts: The raw line offsets.
        """
        self.line_starts = line_starts
        self.line_pref = list(it.accumulate(line_starts))  # prefix sum

    @classmethod
    def from_text(cls, text: str) -> Self:
        """Construct a ``LineMap`` by parsing a GML source string.

        :param text: GML source.
        :return: Constructed ``LineMap`` from parsed contents.
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
        """Converts absolute string index into (line, column) tuple.

        Line and column start from 1.
        :param abs_index: The absolute string index.
        :return: (line_number, column_number), both 1-based.
        """
        line_idx = bisect.bisect_right(self.line_starts, abs_index) - 1
        line_start_index = self.line_starts[line_idx]
        return line_idx + 1, (abs_index - line_start_index) + 1

    def get_abs_index(self, line: int, col: int) -> int:
        """Convert line and column into absolute index.

        Line and column start from 1.
        :param line: Line index.
        :param col: Column index.
        :return: Absolute string index (starts from 0).
        """
        return self.line_pref[line - 1] + col - 1
