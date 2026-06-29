"""Common executor utils."""

import collections.abc as col
import traceback
from dataclasses import dataclass

from clunkster.pipeline.cache import FileBuildCache
from clunkster.pipeline.events import event
from clunkster.pipeline.events.context import ExecutionContext
from clunkster.pipeline.task import Task


@dataclass(frozen=True, slots=True)
class ExecuteTaskResult:
    """Result of task execution."""

    task_id: str
    success: bool
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
            stale.append(task)

    return stale, cached


def tasks_apply_results(
    cache: FileBuildCache,
    results: col.Iterable[tuple[Task, ExecuteTaskResult]],
    *,
    assert_no_fail: bool = False,
) -> tuple[int, int]:
    """Apply results of tasks into the cache.

    :param cache: Build cache.
    :param results: Iterable of tasks and their respective results.
    :param assert_no_fail: Assert none of the tasks have failed.
    :return: Number of succeeded tasks and number of failed tasks.
    """
    success = 0
    failed = 0

    for task, result in results:
        if result.success:
            cache.update(task.task_id, task.inputs_hash)
            success += 1
        else:
            print(f'\nTask {task.task_id} failed:\n{result.error}')
            failed += 1

    cache.save()

    if assert_no_fail and failed:
        raise RuntimeError(f'{failed} task(s) failed.')

    return success, failed


def task_exec(task: Task, ctx: ExecutionContext) -> ExecuteTaskResult:
    """Execute the task in mp-friendly way and return task result.

    :param task: Task to execute.
    :param ctx: Execution context.
    :return: Task result.
    """
    # ensure output directories exist
    for out in task.outputs:
        out.parent.mkdir(parents=True, exist_ok=True)
    ctx.sink.emit(event.TaskStarted(task_id=task.task_id))
    try:
        task.execute()
    except Exception:  # noqa: BLE001
        ctx.sink.emit(
            event.TaskFinished(
                task_id=task.task_id,
                success=False,
            )
        )
        return ExecuteTaskResult(
            task_id=task.task_id,
            success=False,
            error=traceback.format_exc(),
        )
    else:
        ctx.sink.emit(
            event.TaskFinished(
                task_id=task.task_id,
                success=True,
            )
        )
        return ExecuteTaskResult(
            task_id=task.task_id,
            success=True,
            error='',
        )
