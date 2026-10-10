"""Unit tests for build cache."""

import json
import os
from pathlib import Path
from typing import override

import pytest

from clunkster.pipeline import task as my_task
from clunkster.pipeline.cache import FileBuildCache

# far enough in the past to be outside the racy window
OLD_MTIME_NS = 1_000_000_000_000_000_000
SECOND = 1_000_000_000


class TaskNoop(my_task.TaskGeneric):
    """Task that does nothing."""

    @override
    def execute(self) -> None:
        pass


def make_task(file_in: Path, file_out: Path) -> TaskNoop:
    """Make a fresh task (properties are cached per instance)."""
    return TaskNoop(task_id='t', inputs=(file_in,), outputs=(file_out,))


def write_old(path: Path, text: str) -> None:
    """Write a file and backdate it."""
    path.write_text(text)
    os.utime(path, ns=(OLD_MTIME_NS, OLD_MTIME_NS))


def forbid_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any hashing attempt fail."""

    def fail(*_: Path) -> str:
        raise AssertionError('Input was hashed')

    monkeypatch.setattr(my_task, 'file_hash', fail)


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Input, output and cache files, built once."""
    file_in = tmp_path / 'in.txt'
    file_out = tmp_path / 'out.txt'
    write_old(file_in, 'abc')
    file_out.write_text('out')

    cache = FileBuildCache(tmp_path / 'cache.json')
    task = make_task(file_in, file_out)
    assert not cache.task_is_fresh(task)
    cache.update(task.task_id, task.inputs_hash, task.inputs_stats)
    cache.save()
    return file_in, file_out, tmp_path / 'cache.json'


def test_unchanged_stats_skip_hashing(
    files: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unchanged inputs are fresh without being read."""
    file_in, file_out, file_cache = files
    forbid_hashing(monkeypatch)
    assert FileBuildCache(file_cache).task_is_fresh(
        make_task(file_in, file_out)
    )


def test_touched_same_content(files: tuple[Path, Path, Path]) -> None:
    """Rewritten input with same content (git checkout) is still fresh."""
    file_in, file_out, file_cache = files
    file_in.unlink()
    write_old(file_in, 'abc')
    os.utime(file_in, ns=(OLD_MTIME_NS + SECOND, OLD_MTIME_NS + SECOND))

    cache = FileBuildCache(file_cache)
    task = make_task(file_in, file_out)
    assert cache.task_is_fresh(task)
    # stats got refreshed
    assert cache.stats['t'] == task.inputs_stats


def test_changed_content(files: tuple[Path, Path, Path]) -> None:
    """Changed input content makes the task stale."""
    file_in, file_out, file_cache = files
    write_old(file_in, 'abd')
    os.utime(file_in, ns=(OLD_MTIME_NS + SECOND, OLD_MTIME_NS + SECOND))
    assert not FileBuildCache(file_cache).task_is_fresh(
        make_task(file_in, file_out)
    )


def test_missing_output(files: tuple[Path, Path, Path]) -> None:
    """Missing output makes the task stale."""
    file_in, file_out, file_cache = files
    file_out.unlink()
    assert not FileBuildCache(file_cache).task_is_fresh(
        make_task(file_in, file_out)
    )


def test_racy_stats_not_stored(tmp_path: Path) -> None:
    """Stats of just modified inputs aren't trusted."""
    file_in = tmp_path / 'in.txt'
    file_in.write_text('abc')
    task = make_task(file_in, tmp_path / 'out.txt')

    cache = FileBuildCache(tmp_path / 'cache.json')
    cache.update(task.task_id, task.inputs_hash, task.inputs_stats)
    assert 't' not in cache.stats


def test_version_1_cache(
    files: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flat cache from older versions is hashed once, then stat-checked."""
    file_in, file_out, file_cache = files
    hashes = json.loads(file_cache.read_text())['hashes']
    file_cache.write_text(json.dumps(hashes))

    cache = FileBuildCache(file_cache)
    assert cache.task_is_fresh(make_task(file_in, file_out))
    cache.save()

    forbid_hashing(monkeypatch)
    assert FileBuildCache(file_cache).task_is_fresh(
        make_task(file_in, file_out)
    )
