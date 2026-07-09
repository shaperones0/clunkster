"""GML script static analysis.

The purpose of the analysis is to find "guard scripts", like this:
```gml
if room_is_stageA() {
    ...
}
```
anything inside this should be considered as only "referrable" if
current room is a part of ``stageA`` cluster.
"""

import bisect
import dataclasses
import re
from typing import Self


@dataclasses.dataclass(frozen=True)
class CodeRangeIgnore:
    """Range for ignored lines (comments)."""

    start: int
    end: int


@dataclasses.dataclass(frozen=True)
class CodeRangeContext:
    """Range for context stack items."""

    start: int
    end: int
    contexts: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class CodeMarkContext:
    """Helper marker for a singular context stack slice."""

    start: int
    contexts: tuple[str, ...]


class GmlIndex:
    """Static GML files analysis."""

    def __init__(
        self,
        *,
        text: str,
        ignored_ranges: list[CodeRangeIgnore],
        context_ranges: list[CodeRangeContext],
    ) -> None:
        """Static GML analyzer.

        This constructor is normally not used by user code, use
        the secondary constructors, such as ``from_text``.
        :param text: Script source.
        :param ignored_ranges: Ignored ranges (sorted by range start, asc).
        :param context_ranges: Context ranges (sorted by range start, asc).
        """
        self.text = text
        self.ignored_ranges = ignored_ranges
        self.context_ranges = context_ranges

    @classmethod
    def from_text(cls, text: str) -> Self:
        """Build analyzer from script source.

        Effectively, parse given text.
        :param text: Script source.
        :return: Analyzer based on parsed data.
        """
        ignored_ranges: list[CodeRangeIgnore] = []
        context_ranges: list[CodeRangeContext] = []

        pattern = re.compile(
            r'(?P<string>".*?"|\'.*?\')|'
            r'(?P<line_comment>//[^\n]*)|'
            r'(?P<block_comment>/\*.*?\*/)|'
            r'(?P<guard>if\s+[a-zA-Z0-9_]+\s*\(\)\s*\{)|'
            r'(?P<lbrace>\{)|'
            r'(?P<rbrace>})',
            re.MULTILINE | re.DOTALL,
        )

        context_stack: list[CodeMarkContext] = []
        bracket_depth = 0
        guard_depths: dict[int, str] = {}

        for match in pattern.finditer(text):
            kind = match.lastgroup
            start, end = match.span()

            if kind in {'string', 'line_comment', 'block_comment'}:
                ignored_ranges.append(CodeRangeIgnore(start, end))

            elif kind == 'guard':
                guard_name = re.search(r'if\s+([a-zA-Z0-9_]+)', match.group())
                assert guard_name is not None
                guard_name = guard_name.group(1)
                bracket_depth += 1
                guard_depths[bracket_depth] = guard_name

                context_stack.append(
                    CodeMarkContext(end, tuple(guard_depths.values()))
                )

            elif kind == 'lbrace':
                bracket_depth += 1

            elif kind == 'rbrace':
                if bracket_depth in guard_depths:
                    block_info = context_stack.pop()
                    context_ranges.append(
                        CodeRangeContext(
                            block_info.start,
                            start,
                            block_info.contexts,
                        )
                    )
                    del guard_depths[bracket_depth]

                bracket_depth -= 1

        context_ranges.sort(key=lambda x: x.start)

        return cls(
            text=text,
            ignored_ranges=ignored_ranges,
            context_ranges=context_ranges,
        )

    def is_ignored_at(self, char_index: int) -> bool:
        """Returns True if the char index falls inside a string or comment.

        :param char_index: Index to check.
        :return: True is ignored.
        """
        idx = (
            bisect.bisect_right(
                [r.start for r in self.ignored_ranges], char_index
            )
            - 1
        )
        if idx >= 0:
            item = self.ignored_ranges[idx]
            if item.start <= char_index < item.end:
                return True
        return False

    def get_contexts_at(self, char_index: int) -> tuple[str, ...]:
        """Returns the list of active guard contexts for the given char index.

        :param char_index: Index to check.
        :return: List of script guards.
        """
        idx = (
            bisect.bisect_right(
                [r.start for r in self.context_ranges], char_index
            )
            - 1
        )

        while idx >= 0:
            item = self.context_ranges[idx]
            if item.start <= char_index < item.end:
                return item.contexts
            idx -= 1

        return ()
