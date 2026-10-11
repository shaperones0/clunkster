"""Unit tests for task execution."""

import concurrent.futures
from pathlib import Path

import pytest

from clunkster.pipeline import run as my_run
from clunkster.pipeline import task as my_task
from clunkster.pipeline.cache import FileBuildCache


@pytest.mark.parametrize(
    'pool_cls',
    [
        concurrent.futures.ThreadPoolExecutor,
        concurrent.futures.ProcessPoolExecutor,
    ],
)
def test_run(
    tmp_path: Path, pool_cls: type[concurrent.futures.Executor]
) -> None:
    """Tasks run, successes get cached, failures are reported."""
    file_in = tmp_path / 'in.txt'
    file_in.write_text('abc')
    file_gone = tmp_path / 'gone.txt'
    file_gone.write_text('abc')

    ok = my_task.TaskCopy((file_in, tmp_path / 'out' / 'ok.txt'))
    bad = my_task.TaskCopy((file_gone, tmp_path / 'out' / 'bad.txt'))
    file_gone.unlink()

    cache = FileBuildCache(tmp_path / 'cache.json')
    done: list[my_run.TaskDone] = []
    with pool_cls() as pool:
        failures = my_run.tasks_run(
            [ok, bad], cache, pool, on_done=done.append
        )

    assert (tmp_path / 'out' / 'ok.txt').read_text() == 'abc'
    assert sorted(d.task.task_id for d in done) == sorted([
        ok.task_id,
        bad.task_id,
    ])
    # process pools report process ids, thread pools thread names
    if pool_cls is concurrent.futures.ProcessPoolExecutor:
        assert all(d.worker.isdigit() for d in done)
    else:
        assert all('ThreadPoolExecutor' in d.worker for d in done)
    assert [d.task for d in done if d.error] == [bad]
    assert [f.task_id for f in failures] == [bad.task_id]
    assert 'FileNotFoundError' in failures[0].error

    # only the success got cached, and the cache was saved
    cache = FileBuildCache(tmp_path / 'cache.json')
    stale, cached = my_run.tasks_filter_stale([ok], cache)
    assert (stale, cached) == ([], 1)
    assert bad.task_id not in cache.data
