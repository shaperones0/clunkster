"""Unit tests for reference scan cache."""

import time
from pathlib import Path

from clunkster.analyze.scan_cache import FileMatch, ScanCache

OLD = (1_000_000_000_000_000_000, 10, 1)
MATCHES = (
    FileMatch(5, 1, 6, 'sprA', ('room_is_a',)),
    FileMatch(9, 2, 1, 'b', ()),
)


def test_roundtrip(tmp_path: Path) -> None:
    """Matches survive saving and loading while stat and names match."""
    file_cache = tmp_path / 'cache.json'
    cache = ScanCache(file_cache)
    cache.set_names('n1')
    cache.put(tmp_path / 'a.gml', OLD, MATCHES)
    cache.save()

    cache = ScanCache(file_cache)
    cache.set_names('n1')
    assert cache.get(tmp_path / 'a.gml', OLD) == MATCHES
    changed = (OLD[0] + 1, *OLD[1:])
    assert cache.get(tmp_path / 'a.gml', changed) is None


def test_names_change(tmp_path: Path) -> None:
    """Changing scanned names drops everything."""
    cache = ScanCache(tmp_path / 'cache.json')
    cache.set_names('n1')
    cache.put(tmp_path / 'a.gml', OLD, MATCHES)
    cache.set_names('n2')
    assert cache.get(tmp_path / 'a.gml', OLD) is None


def test_unused_dropped(tmp_path: Path) -> None:
    """Files not looked up since the last save are dropped on save."""
    file_cache = tmp_path / 'cache.json'
    cache = ScanCache(file_cache)
    cache.put(tmp_path / 'a.gml', OLD, MATCHES)
    cache.put(tmp_path / 'b.gml', OLD, MATCHES)
    cache.save()

    cache = ScanCache(file_cache)
    assert cache.get(tmp_path / 'a.gml', OLD) == MATCHES
    cache.save()

    cache = ScanCache(file_cache)
    assert cache.get(tmp_path / 'a.gml', OLD) == MATCHES
    assert cache.get(tmp_path / 'b.gml', OLD) is None


def test_racy_not_stored(tmp_path: Path) -> None:
    """Matches of just modified files aren't trusted."""
    cache = ScanCache(tmp_path / 'cache.json')
    recent = (time.time_ns(), *OLD[1:])
    cache.put(tmp_path / 'a.gml', recent, MATCHES)
    assert cache.get(tmp_path / 'a.gml', recent) is None
