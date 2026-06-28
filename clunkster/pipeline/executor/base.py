
import collections.abc as col
from dataclasses import dataclass
import traceback

from clunkster.pipeline.task import Task
from clunkster.pipeline.cache import FileBuildCache
from clunkster.pipeline.events.context import ExecutionContext
from clunkster.pipeline.events import event


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
    """Return stale tasks and number of cached tasks."""

    stale: list[Task] = []
    cached = 0

    for task in tasks:
        if cache.is_fresh(
            task_id=task.task_id,
            current_hash=task.inputs_hash,
            outputs=task.outputs_cached,
        ):
            cached += 1
        else:
            stale.append(task)

    return stale, cached


def tasks_apply_results(
    cache: FileBuildCache,
    results: col.Iterable[tuple[Task, ExecuteTaskResult]],
) -> tuple[int, int]:
    success = 0
    failed = 0

    for task, result in results:
        if result.success:
            cache.update(task.task_id, task.inputs_hash)
            success += 1
        else:
            print(
                f"\nTask {task.task_id} failed:"
                f"\n{result.error}"
            )
            failed += 1

    cache.save()

    if failed:
        raise RuntimeError(
            f"{failed} task(s) failed."
        )

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
    except Exception as err:  # noqa: BLE001
        ctx.sink.emit(event.TaskFinished(
            task_id=task.task_id,
            success=False,
        ))
        return ExecuteTaskResult(
            task_id=task.task_id,
            success=False,
            error=traceback.format_exc(),
        )
    else:
        ctx.sink.emit(event.TaskFinished(
            task_id=task.task_id,
            success=True,
        ))
        return ExecuteTaskResult(
            task_id=task.task_id,
            success=True,
            error='',
        )

