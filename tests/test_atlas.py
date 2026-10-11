"""Unit tests for texture atlas geometry."""

from clunkster import atlas


def test_union_area() -> None:
    """Overlaps are counted once."""
    assert atlas.union_area([(0, 0, 10, 10), (5, 5, 10, 10)]) == 175
    assert atlas.union_area([(0, 0, 10, 10), (2, 2, 3, 3)]) == 100
    assert atlas.union_area([(0, 0, 2, 2), (5, 0, 2, 2)]) == 8


def test_contained_stored_in_container() -> None:
    """Regions inside another aren't stored separately."""
    stored = atlas.merge_regions(
        [(0, 0, 64, 64), (16, 16, 32, 32), (100, 0, 8, 8)], max_waste=0
    )
    assert stored[16, 16, 32, 32] == (0, 0, 64, 64)
    assert stored[0, 0, 64, 64] == (0, 0, 64, 64)
    assert stored[100, 0, 8, 8] == (100, 0, 8, 8)


def test_overlap_merged_when_cheap() -> None:
    """Slightly shifted selections of the same prop get merged."""
    stored = atlas.merge_regions(
        [(0, 0, 32, 32), (2, 1, 32, 32)], max_waste=0.25
    )
    assert stored[0, 0, 32, 32] == stored[2, 1, 32, 32] == (0, 0, 34, 33)


def test_overlap_kept_apart_when_wasteful() -> None:
    """Tall and wide regions crossing each other stay separate."""
    tall, wide = (100, 0, 10, 300), (0, 100, 300, 10)
    stored = atlas.merge_regions([tall, wide], max_waste=0.25)
    assert stored[tall] == tall
    assert stored[wide] == wide


def test_grid_rects() -> None:
    """Equal cells merge into rectangles, others stay apart."""
    cells = {
        (0, 0): 'a', (1, 0): 'a', (2, 0): 'b',
        (0, 1): 'a', (1, 1): 'a', (2, 1): 'b',
        (0, 2): 'a',
    }  # fmt: skip
    rects = atlas.grid_rects(cells)
    assert sorted(rects) == [
        (0, 0, 2, 2, 'a'),
        (0, 2, 1, 1, 'a'),
        (2, 0, 1, 2, 'b'),
    ]
    covered = {
        (x + dx, y + dy)
        for x, y, w, h, _ in rects
        for dx in range(w)
        for dy in range(h)
    }
    assert covered == set(cells)
