"""Task execution."""

import collections.abc as col
import concurrent.futures
import traceback
from dataclasses import dataclass

from clunkster.pipeline.cache import FileBuildCache
from clunkster.pipeline.task import Task


@dataclass(frozen=True, slots=True)
class TaskFailure:
    """Failed task."""

    task_id: str
    # formatted traceback
    error: str


def tasks_filter_stale(
    tasks: col.Iterable[Task],
    cache: FileBuildCache,
) -> tuple[list[Task], int]:
    """Filter tasks by their cache status.

    :param tasks: Tasks to filter.
    :param cache: Build cache.
    :return: List of stale tasks (needs to be executed) and number of cached
      tasks.
    """
    stale: list[Task] = []
    cached = 0

    for task in tasks:
        if cache.task_is_fresh(task):
            cached += 1
        else:
            # snapshot inputs before execution, so edits made during the
            #  build are picked up by the next one
            _ = task.inputs_stats, task.inputs_hash
            stale.append(task)

    # freshness checks may have refreshed input stats
    cache.save()

    return stale, cached


def task_execute(task: Task) -> str | None:
    """Execute the task.

    Module level function, so that process pools can pickle it.

    :param task: Task to execute.
    :return: Formatted traceback if the task failed, ``None`` otherwise.
    """
    for out in task.outputs:
        out.parent.mkdir(parents=True, exist_ok=True)
    try:
        task.execute()
    except Exception:  # ruff: ignore[blind-except]
        return traceback.format_exc()
    return None


def tasks_run(
    tasks: col.Iterable[Task],
    cache: FileBuildCache,
    pool: concurrent.futures.Executor,
    *,
    on_done: col.Callable[[Task, str | None], None] | None = None,
) -> list[TaskFailure]:
    """Execute tasks in the given pool and record successes in the cache.

    Tasks are executed as is, filter them with ``tasks_filter_stale`` first.
    Use a thread pool for IO-bound tasks and a process pool for CPU-bound
    ones.

    :param tasks: Tasks to execute.
    :param cache: Build cache, saved when done.
    :param pool: Executor to run the tasks in.
    :param on_done: Called in the calling thread after each task with the
      task and its error (``None`` on success), e.g. to advance a progress
      bar.
    :return: Failed tasks.
    """
    futures = {pool.submit(task_execute, task): task for task in tasks}
    failures: list[TaskFailure] = []
    try:
        for future in concurrent.futures.as_completed(futures):
            task = futures[future]
            error = future.result()
            if error is None:
                cache.update(task.task_id, task.inputs_hash, task.inputs_stats)
            else:
                failures.append(TaskFailure(task_id=task.task_id, error=error))
            if on_done is not None:
                on_done(task, error)
    finally:
        cache.save()
    return failures
