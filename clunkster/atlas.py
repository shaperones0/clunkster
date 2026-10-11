"""Texture atlas geometry."""

import collections.abc as col
import itertools as it
import operator

# left, top, width, height
Rect = tuple[int, int, int, int]


def rect_contains(outer: Rect, inner: Rect) -> bool:
    """Check whether ``inner`` lies fully within ``outer``."""
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[0] + inner[2] <= outer[0] + outer[2]
        and inner[1] + inner[3] <= outer[1] + outer[3]
    )


def rect_overlaps(a: Rect, b: Rect) -> bool:
    """Check whether two rectangles share any area."""
    return (
        a[0] < b[0] + b[2]
        and b[0] < a[0] + a[2]
        and a[1] < b[1] + b[3]
        and b[1] < a[1] + a[3]
    )


def rect_bounds(rects: col.Iterable[Rect]) -> Rect:
    """Get the bounding rectangle."""
    rects = list(rects)
    left = min(r[0] for r in rects)
    top = min(r[1] for r in rects)
    right = max(r[0] + r[2] for r in rects)
    bottom = max(r[1] + r[3] for r in rects)
    return left, top, right - left, bottom - top


def union_area(rects: col.Sequence[Rect]) -> int:
    """Get the area covered by rectangles (overlaps counted once)."""
    xs = sorted({x for r in rects for x in (r[0], r[0] + r[2])})
    area = 0
    for x1, x2 in it.pairwise(xs):
        spans = sorted(
            (r[1], r[1] + r[3])
            for r in rects
            if r[0] <= x1 and x2 <= r[0] + r[2]
        )
        covered = 0
        end = None
        for top, bottom in spans:
            if end is None or top > end:
                covered += bottom - top
                end = bottom
            elif bottom > end:
                covered += bottom - end
                end = bottom
        area += covered * (x2 - x1)
    return area


def _find(parent: list[int], item: int) -> int:
    """Find the root of an item in a union-find forest."""
    path = [item]
    while parent[path[-1]] != path[-1]:
        path.append(parent[path[-1]])
    for node in path:
        parent[node] = path[-1]
    return path[-1]


def merge_regions(
    rects: col.Iterable[Rect], max_waste: float
) -> dict[Rect, Rect]:
    """Decide how to store overlapping regions of one image.

    Regions overlapping each other (directly or through others) form
    groups. A group is stored as its bounding rectangle when that adds at
    most ``max_waste`` times the group's covered area of pixels nobody uses.
    Otherwise its regions are stored apart, except regions lying fully
    within another, which are stored as part of it.

    :param rects: Regions.
    :param max_waste: Allowed unused share of a merged group.
    :return: Every region mapped to the region it's stored as (which
      contains it).
    """
    unique = sorted(set(rects), key=lambda r: (-r[2] * r[3], r))
    # union-find over overlapping regions
    parent: list[int] = list(range(len(unique)))

    order = sorted(range(len(unique)), key=lambda i: unique[i][0])
    for pos, i in enumerate(order):
        a = unique[i]
        for j in order[pos + 1 :]:
            b = unique[j]
            if b[0] >= a[0] + a[2]:
                break
            if rect_overlaps(a, b):
                parent[_find(parent, i)] = _find(parent, j)

    groups: dict[int, list[Rect]] = {}
    for i, rect in enumerate(unique):
        groups.setdefault(_find(parent, i), []).append(rect)

    stored: dict[Rect, Rect] = {}
    for members in groups.values():
        bounds = rect_bounds(members)
        covered = union_area(members)
        if bounds[2] * bounds[3] - covered <= max_waste * covered:
            for rect in members:
                stored[rect] = bounds
            continue
        # largest first, so containers are known before what they contain
        tops: list[Rect] = []
        for rect in members:
            container = next((t for t in tops if rect_contains(t, rect)), None)
            if container is None:
                tops.append(rect)
                container = rect
            stored[rect] = container
    return stored


def grid_rects[K](
    cells: col.Mapping[tuple[int, int], K],
) -> list[tuple[int, int, int, int, K]]:
    """Merge grid cells with equal keys into rectangles.

    Greedy: from the top left, a rectangle grows right as long as cells have
    the same key, then down as long as whole rows below do.

    :param cells: Cells (column, row) and their keys; missing cells are
      empty.
    :return: Rectangles (column, row, columns, rows, key).
    """
    used: set[tuple[int, int]] = set()
    rects: list[tuple[int, int, int, int, K]] = []
    for cx, cy in sorted(cells, key=operator.itemgetter(1, 0)):
        if (cx, cy) in used:
            continue
        key = cells[cx, cy]

        def free(x: int, y: int, key: K = key) -> bool:
            return (
                (x, y) not in used and (x, y) in cells and cells[x, y] == key
            )

        width = 1
        while free(cx + width, cy):
            width += 1
        height = 1
        while all(free(cx + dx, cy + height) for dx in range(width)):
            height += 1
        for dy in range(height):
            used.update((cx + dx, cy + dy) for dx in range(width))
        rects.append((cx, cy, width, height, key))
    return rects
