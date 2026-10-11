"""Task execution."""

import collections.abc as col
import concurrent.futures
import os
import threading
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


@dataclass(frozen=True, slots=True)
class TaskDone:
    """Finished task, as reported to ``tasks_run`` callback."""

    task: Task
    # process id in process pools, thread name in thread pools
    worker: str
    # formatted traceback, ``None`` on success
    error: str | None
    # tasks that are running right now (best effort, e.g. process pools
    #  report tasks queued for a worker as running too)
    running: tuple[Task, ...]


def task_execute(task: Task) -> tuple[str, str | None]:
    """Execute the task.

    Module level function, so that process pools can pickle it.

    :param task: Task to execute.
    :return: Worker that executed it (process id or thread name), and
      formatted traceback if the task failed, ``None`` otherwise.
    """
    thread = threading.current_thread()
    worker = (
        str(os.getpid()) if thread is threading.main_thread() else thread.name
    )
    for out in task.outputs:
        out.parent.mkdir(parents=True, exist_ok=True)
    try:
        task.execute()
    except Exception:  # ruff: ignore[blind-except]
        return worker, traceback.format_exc()
    return worker, None


# how many of the oldest unfinished tasks to check for being running
_RUNNING_WINDOW = 64


def tasks_run(
    tasks: col.Iterable[Task],
    cache: FileBuildCache,
    pool: concurrent.futures.Executor,
    *,
    on_done: col.Callable[[TaskDone], None] | None = None,
) -> list[TaskFailure]:
    """Execute tasks in the given pool and record successes in the cache.

    Tasks are executed as is, filter them with ``tasks_filter_stale`` first.
    Use a thread pool for IO-bound tasks and a process pool for CPU-bound
    ones.

    :param tasks: Tasks to execute.
    :param cache: Build cache, saved when done.
    :param pool: Executor to run the tasks in.
    :param on_done: Called in the calling thread after each task, e.g. to
      show progress. Workers don't report anything beyond their results.
    :return: Failed tasks.
    """
    futures = {pool.submit(task_execute, task): task for task in tasks}
    # pools start tasks in submission order, so running ones are among the
    #  oldest unfinished
    order = list(futures)
    oldest = 0
    failures: list[TaskFailure] = []
    try:
        for future in concurrent.futures.as_completed(futures):
            task = futures[future]
            worker, error = future.result()
            if error is None:
                cache.update(task.task_id, task.inputs_hash, task.inputs_stats)
            else:
                failures.append(TaskFailure(task_id=task.task_id, error=error))
            if on_done is None:
                continue

            while oldest < len(order) and order[oldest].done():
                oldest += 1
            running = tuple(
                futures[f]
                for f in order[oldest : oldest + _RUNNING_WINDOW]
                if f.running()
            )
            on_done(
                TaskDone(
                    task=task, worker=worker, error=error, running=running
                )
            )
    finally:
        cache.save()
    return failures
