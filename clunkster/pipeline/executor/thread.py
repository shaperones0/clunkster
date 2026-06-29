"""Threading executor."""

import collections.abc as col
import concurrent.futures

from clunkster.pipeline.cache import FileBuildCache
from clunkster.pipeline.events import event
from clunkster.pipeline.events.context import ExecutionContext
from clunkster.pipeline.events.dispatcher import EventDispatcher
from clunkster.pipeline.events.sink import DirectEventSink
from clunkster.pipeline.executor import base
from clunkster.pipeline.executor.base import ExecuteTaskResult
from clunkster.pipeline.task import Task


def execute_threaded(
    tasks: col.Iterable[Task],
    cache: FileBuildCache,
    dispatcher: EventDispatcher,
    *,
    max_workers: int | None = None,
) -> None:
    """Execute given tasks with threading executor.

    :param tasks: Tasks to execute.
    :param cache: Build cache.
    :param dispatcher: Event dispatcher for the workers.
    :param max_workers: Maximum number of worker processes.
    """
    tasks, _ = base.tasks_filter_stale(tasks, cache)
    if not tasks:
        return

    total_tasks = len(tasks)
    dispatcher.dispatch(
        event.ProgressStart(
            worker_id='main', task_id='overall', total=total_tasks
        )
    )

    sink = DirectEventSink(dispatcher)
    ctx = ExecutionContext(sink=sink)

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:
        futures = {
            executor.submit(base.task_exec, task, ctx): task for task in tasks
        }

        def stream_results() -> col.Iterator[tuple[Task, ExecuteTaskResult]]:
            for i, f in enumerate(
                concurrent.futures.as_completed(futures), start=1
            ):
                yield futures[f], f.result()
                # update main progress bar
                dispatcher.dispatch(
                    event.ProgressAdvance(
                        worker_id='main', task_id='overall', completed=i
                    )
                )

        base.tasks_apply_results(cache, stream_results())

    dispatcher.dispatch(
        event.ProgressCompleted(worker_id='main', task_id='overall')
    )
