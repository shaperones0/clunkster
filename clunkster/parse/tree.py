"""Parse tree.yyd files."""

import collections.abc as col
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TreeNode:
    """Structural node in the ``tree.yyd``."""

    line_num: int
    depth: int
    is_folder: bool
    name: str
    parent_path: tuple[str, ...]


def nodes(lines: col.Iterable[str]) -> col.Iterator[TreeNode]:
    """Iterate through ``tree.yyd``, yield structural data.

    Unlike simple parser, this doesn't collapse duplicates, making
    it suitable for linting.

    :param lines: Input lines.
    :return: Iterator of tree nodes.
    """
    stack: list[str] = []

    for line_num, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue

        depth = 0
        for char in raw_line:
            if char == '\t':
                depth += 1
            else:
                break

        content = raw_line.strip()

        while len(stack) > depth:
            stack.pop()

        is_folder = content.startswith('+')
        name = (
            content[1:] if (is_folder or content.startswith('|')) else content
        )

        yield TreeNode(
            line_num=line_num,
            depth=depth,
            is_folder=is_folder,
            name=name,
            parent_path=tuple(stack),
        )

        if is_folder:
            stack.append(name)


def parse(
    tree_lines: col.Iterable[str],
) -> col.Iterator[tuple[str, tuple[str, ...]]]:
    """Parse tree.yyd files and yield asset names and their paths.

    Paths are tuples of folder names; actual asset name is not appended.
    :param tree_lines: Lines of the tree.yyd file.
    :return: Iterator of asset names and their paths.
    """
    stack: list[tuple[int, str]] = []
    for line in tree_lines:
        if not line.strip():
            continue

        line_stripped = line.lstrip()
        indent = len(line) - len(line_stripped)
        name = line_stripped[1:].strip()

        while stack and stack[-1][0] >= indent:
            stack.pop()

        if line_stripped[0] == '+':
            stack.append((indent, name))
        elif line_stripped[0] == '|':
            folders = [folder_name for _, folder_name in stack]
            yield name, tuple(folders)
