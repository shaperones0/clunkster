"""Dynamically extract code blocks for README."""

import collections.abc as col
import re
import textwrap
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Self

# handle arbitrary spaces
RX_START = re.compile(r'^\s*#\s*---\s*COG_START:\s*([A-Za-z0-9_]+)\s*---')
RX_END = re.compile(r'^\s*#\s*---\s*COG_END:\s*([A-Za-z0-9_]+)\s*---')
RX_MD = re.compile(r'^\s*#\s*MD:\s?(.*)')


class SnippetType(Enum):
    """Snippet type."""

    PYTHON = auto()
    MD = auto()


@dataclass
class Snippet:
    """Snippet struct for easier rendering and distinction."""

    type: SnippetType
    content: str

    @classmethod
    def from_code(cls, code: str) -> Self:
        """Make a snippet out of Python code.

        :param code: Python code.
        """
        return cls(
            type=SnippetType.PYTHON,
            content=code,
        )

    @classmethod
    def from_md(cls, md: str) -> Self:
        """Make a snippet out of Markdown text.

        :param md: Markdown text.
        """
        return cls(
            type=SnippetType.MD,
            content=md,
        )


class SnippetExtractor:
    """Snippet extractor."""

    def __init__(self, snippets: dict[str, list[Snippet]]) -> None:
        """Initialize SnippetExtractor.

        Use from_lines or from_file_path constructors preferably.
        :param snippets: Snippets dictionary.
        """
        self.snippets: dict[str, list[Snippet]] = snippets

    @classmethod
    def from_lines(cls, lines: list[str]) -> Self:
        """Construct extractor by parsing given lines for snippets.

        :param lines: Lines to parse.
        """
        return cls(extract_snippets_lines(lines))

    @classmethod
    def from_file_path(cls, file_path: str) -> Self:
        """Construct extractor by parsing given file path.

        :param file_path: Path of file to parse.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Source file '{file_path}' not found.")

        return cls.from_lines(path.read_text(encoding='utf-8').splitlines())

    def extract(self, snippet_id: str) -> list[Snippet]:
        """Find snippet by id.

        :param snippet_id: Snippet id to find.
        :return: Found snippet.
        """
        if snippet_id not in self.snippets:
            raise ValueError(f"Snippet '{snippet_id}' not found.")
        return self.snippets[snippet_id]


def _format_snippet(lines: list[str]) -> list[Snippet]:  # noqa: C901, PLR0912
    """Parse a raw snippet, interleaving Markdown text and Python code fences.

    :param lines: Snippet lines.
    :return: Formatted snippet contents.
    """
    # dedent whole block to preserve relative indentation
    text = textwrap.dedent('\n'.join(lines))
    dedented_lines = text.splitlines()

    chunks: list[tuple[str, list[str]]] = []
    is_in_md = False
    current_chunk: list[str] = []

    for line in dedented_lines:
        md_match = RX_MD.match(line)
        is_blank = not line.strip()

        if md_match:
            if not is_in_md and current_chunk:
                chunks.append(('CODE', current_chunk))
                current_chunk = []
            is_in_md = True
            current_chunk.append(md_match.group(1))
        elif is_blank:
            # blank lines inherits the current state
            #  so we don't break fences randomly
            current_chunk.append(line if not is_in_md else '')
        else:
            if is_in_md and current_chunk:
                chunks.append(('MD', current_chunk))
                current_chunk = []
            is_in_md = False
            current_chunk.append(line)

    if current_chunk:
        chunks.append(('MD' if is_in_md else 'CODE', current_chunk))

    out: list[Snippet] = []

    for ctype, clines in chunks:
        # strip trailing/leading blank lines
        while clines and not clines[0].strip():
            clines.pop(0)
        while clines and not clines[-1].strip():
            clines.pop()

        if not clines:
            continue

        joined = '\n'.join(clines)
        if ctype == 'MD':
            out.append(
                Snippet(
                    type=SnippetType.MD,
                    content=joined,
                )
            )
        else:
            out.append(
                Snippet(
                    type=SnippetType.PYTHON,
                    content=joined,
                )
            )

    return out


def snippets_render(*snippets: Snippet | str) -> str:  # noqa: C901, PLR0912
    """Render sequence of snippets to Markdown.

    :param snippets: Snippet sequence.
    :return: Rendered Markdown.
    """
    blocks: list[str] = []
    fence = chr(96) * 3  # don't ask

    types: list[SnippetType] = []
    for idx, snippet in enumerate(snippets):
        if isinstance(snippet, str):
            if idx > 0:
                types.append(types[idx - 1])
            else:
                types.append(SnippetType.MD)
        elif isinstance(snippet, Snippet):
            types.append(snippet.type)
        else:
            raise NotImplementedError

    for idx, snippet in enumerate(snippets):
        if isinstance(snippet, str):
            new_block = snippet
        elif isinstance(snippet, Snippet):
            new_block = snippet.content
        else:
            raise NotImplementedError

        prev_type: SnippetType | None = types[idx - 1] if idx > 0 else None
        next_type: SnippetType | None = (
            types[idx + 1] if idx < len(snippets) - 1 else None
        )

        if types[idx] == SnippetType.PYTHON:
            if prev_type != SnippetType.PYTHON:
                new_block = f'{fence}python\n{new_block}'
            if next_type != SnippetType.PYTHON:
                new_block = f'{new_block}\n{fence}'

        blocks.append(new_block)

    return '\n\n'.join(blocks)


def extract_snippets_lines(
    lines: col.Iterable[str],
) -> dict[str, list[Snippet]]:
    """Scans given lines and returns contents of found snippets.

    Looks for the markers:
    ::
        # --- COG_START: <ID> ---
        # --- COG_END: <ID> ---

    :param lines: Lines to scan.
    :return: Mapping of ``snippet_id`` to ``snippet_content``.
    """
    cur_snippet: str | None = None
    cur_lines: list[str] = []
    snippets: dict[str, list[Snippet]] = {}
    for line_num, line in enumerate(lines, start=1):
        start_match = RX_START.search(line)
        end_match = RX_END.search(line)

        if start_match:
            if cur_snippet is not None:
                raise RuntimeError(
                    f'Line {line_num}: Nested snippets not allowed. '
                    f"Already inside '{cur_snippet}'."
                )
            cur_snippet = start_match.group(1)
            continue

        if end_match:
            end_id = end_match.group(1)
            if cur_snippet is None:
                raise RuntimeError(
                    f"Line {line_num}: Found COG_END for '{end_id}' "
                    f'but no snippet is active.'
                )
            if cur_snippet != end_id:
                raise RuntimeError(
                    f'Line {line_num}: Mismatched COG_END. Expected '
                    f"'{cur_snippet}', got '{end_id}'."
                )
            assert cur_snippet is not None  # redundant, makes type hints happy
            if cur_snippet in snippets:
                raise RuntimeError(
                    f"Snippet ID '{cur_snippet}' is duplicated."
                )

            snippets[cur_snippet] = _format_snippet(cur_lines)

            cur_lines.clear()
            cur_snippet = None
            continue

        if cur_snippet is not None:
            cur_lines.append(line)

    if cur_snippet is not None:
        raise RuntimeError(
            f'End of file reached, but snippet '
            f"'{cur_snippet}' was never closed."
        )

    return snippets
