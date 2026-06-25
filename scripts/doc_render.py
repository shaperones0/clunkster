"""Render sequence of snippets."""

from enum import Enum, auto
from dataclasses import dataclass
from typing import Self
import collections.abc as col

from scripts.doc_snippets import SnippetType, Snippet


def render(inp: col.Iterable[Snippet], delim_same: str = '\n\n', delim_diff: str = '\n\n') -> str:
    """Render sequence of snippets into Markdown document.

    :param inp: Input stream of snippets.
    :param delim_same: Delimiter between blocks of the same type.
    :param delim_diff: Delimiter between blocks of the different type.
    :return: Rendered string.
    """

    blocks: list[str] = []
    fence = chr(96) * 3
    for snippet in _snip_rle(inp, delim=delim_same):
        # guaranteed to be surrounded with not same type blocks
        match snippet.type:
            case SnippetType.MD:
                blocks.append(snippet.content.strip('\n'))
            case SnippetType.PYTHON:
                blocks.append(f"{fence}py\n{snippet.content.strip('\n')}\n{fence}")
    return delim_diff.join(blocks)


def _snip_rle(inp: col.Iterable[Snippet], delim: str = '\n\n') -> col.Iterator[Snippet]:
    """Merge blocks of snippets with a single type into single snippets.

    :param inp: Input stream of snippets.
    :param delim: Delimiter of joined content.
    :return: Output stream of joined snippets. No 2 adjacent snippets have same
      type.
    """

    cur_type: SnippetType = SnippetType.MD
    cur_parts: list[str] = []
    for snippet in inp:
        if snippet.type.name == cur_type.name:  # what the fuck
            cur_parts.append(snippet.content)
            continue

        # new type: yield new snippet
        if cur_parts:
            yield Snippet(
                type=cur_type,
                content=delim.join(cur_parts),
            )
            cur_parts[:] = [snippet.content]
        cur_type = snippet.type
    if cur_parts:
        yield Snippet(
            type=cur_type,
            content=delim.join(cur_parts),
        )
