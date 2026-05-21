"""Parse index.yyd files."""

import collections.abc as col


def parse(index_lines: col.Iterable[str]) -> col.Iterator[str | None]:
    """Parse index.yyd file.

    Parses the file as is, maintaining empty lines.
    :param index_lines: Lines of the index.yyd file.
    :return: Iterator of asset names, or Nones if respective line was blank.
    """
    return (line or None for line in index_lines)


def parse_skimmed(index_lines: col.Iterable[str]) -> col.Iterator[str]:
    """Extract asset names from index.yyd file.

    Skips empty lines.
    :param index_lines: Lines of the index.yyd file.
    :return: Iterator of asset names.
    """
    return (line for line in index_lines if line)
