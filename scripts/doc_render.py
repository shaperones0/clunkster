"""Render sequence of snippets."""

from enum import Enum, auto
from dataclasses import dataclass
from typing import Self
import collections.abc as col

from scripts.doc_snippets import SnippetType, Snippet


def render(inp: col.Iterable[Snippet], delim_same_type: dict[str, str] | None = None, delim_diff: str = '\n\n') -> str:
    """Render sequence of snippets into Markdown document.

    :param inp: Input stream of snippets.
    :param delim_same_type: Delimiter between blocks of the same type.
    :param delim_diff: Delimiter between blocks of the different type.
    :return: Rendered string.
    """

    blocks: list[str] = []
    fence = chr(96) * 3
    for snippet in _snip_rle(inp, delim_type=delim_same_type):
        # guaranteed to be surrounded with not same type blocks
        match snippet.type.name:      # what the fuck
            case 'MD':
                blocks.append(snippet.content.strip('\n'))
            case 'PYTHON':
                blocks.append(f"{fence}py\n{snippet.content.strip('\n')}\n{fence}")
    return delim_diff.join(blocks)


def _snip_rle(inp: col.Iterable[Snippet], delim_type: dict[str, str] | None = None) -> col.Iterator[Snippet]:
    """Merge blocks of snippets with a single type into single snippets.

    :param inp: Input stream of snippets.
    :param delim_type: Delimiter of joined content based on type.
    :return: Output stream of joined snippets. No 2 adjacent snippets have same
      type.
    """
    if delim_type is None:
        delim_type = {
            'MD': '',
            'PYTHON': '\n\n',
        }

    cur_type: SnippetType = SnippetType.MD
    cur_parts: list[str] = []
    for snippet in inp:
        if snippet.type.name == cur_type.name:
            cur_parts.append(snippet.content)
            continue

        # new type: yield new snippet
        if bool(''.join(cur_parts).strip()):
            yield Snippet(
                type=cur_type,
                content=delim_type[cur_type.name].join(cur_parts),
            )
        cur_parts[:] = [snippet.content]
        cur_type = snippet.type
    if bool(''.join(cur_parts).strip()):
        yield Snippet(
            type=cur_type,
            content=delim_type[cur_type.name].join(cur_parts),
        )
