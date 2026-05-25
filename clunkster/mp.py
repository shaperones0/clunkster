"""Multiprocessing helpers."""

import collections.abc as col
import math
import multiprocessing


def get_cpu_count() -> int:
    """Get the number of CPU cores available."""
    return multiprocessing.cpu_count()


def split[T](
    sequence: col.Sequence[T], parts: int
) -> col.Iterator[tuple[T, ...]]:
    """Split a sequence into roughly equal parts.

    :param sequence: Input sequence.
    :param parts: Number of parts.
    :return: Iterator of parts.
    """
    assert parts > 0, 'Parts must be greater than 0'

    size = len(sequence)
    chunk_size = math.ceil(size / parts)
    return (
        tuple(sequence[i : min(i + chunk_size, size)])
        for i in range(0, size, chunk_size)
    )
