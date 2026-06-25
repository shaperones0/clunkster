"""Markdown snippet model."""

from enum import Enum, auto
from dataclasses import dataclass
from typing import Self
import collections.abc as col


class SnippetType(Enum):
    """Snippet type."""

    PYTHON = auto()
    MD = auto()


@dataclass(frozen=True, slots=True)
class Snippet:
    """Snippet struct for easier rendering and distinction."""

    type: SnippetType
    content: str


def s_py(code: str) -> Snippet:
    return Snippet(
        type=SnippetType.PYTHON,
        content=code,
    )

def s_md(code: str) -> Snippet:
    return Snippet(
        type=SnippetType.MD,
        content=code,
    )


def snip_rle(inp: col.Iterable[Snippet], delim: str = '\n\n') -> col.Iterator[Snippet]:
    """Merge blocks of snippets with a single type into single snippets.

    :param inp: Input stream of snippets.
    :param delim: Delimiter of joined content.
    :return: Output stream of joined snippets. No 2 adjacent snippets have same
      type.
    """

    cur_type: SnippetType = SnippetType.MD
    cur_parts: list[str] = []
    for snippet in inp:
        if snippet.type == cur_type:
            cur_parts.append(snippet.content)
            continue

        # new type: yield new snippet
        if cur_parts:
            yield Snippet(
                type=cur_type,
                content=delim.join(cur_parts),
            )
            cur_parts.clear()
        cur_type = snippet.type
    if cur_parts:
        yield Snippet(
            type=cur_type,
            content=delim.join(cur_parts),
        )
