"""Parse tree.yyd files."""

import collections.abc as col


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
