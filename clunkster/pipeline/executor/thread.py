"""Threading executor."""

import collections.abc as col
import concurrent.futures
import threading
from dataclasses import replace
from typing import override

from clunkster.pipeline.cache import FileBuildCache
from clunkster.pipeline.events import event as pl_event
from clunkster.pipeline.events.context import ExecutionContext
from clunkster.pipeline.events.dispatcher import EventDispatcher
from clunkster.pipeline.events.sink import DispatchEventSink
from clunkster.pipeline.executor import base
from clunkster.pipeline.executor.base import ExecuteTaskResult
from clunkster.pipeline.task import Task


class ThreadedEventSink(DispatchEventSink):
    """Direct event sink.

    Similar to ``DispatchEventSink``, intended for threaded operations.
    Acquires thread lock before dispatching an event.
    """

    @override
    def __init__(self, dispatcher: EventDispatcher) -> None:
        """Initialize sink with given dispatcher.

        Also gets a lock.
        """
        super().__init__(dispatcher)
        self._lock = threading.Lock()

    @override
    def emit(self, event: pl_event.Event) -> None:
        worker_id = threading.current_thread().name
        worker_event = replace(event, worker_id=worker_id)
        with self._lock:
            self._dispatcher.dispatch(worker_event)


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
        pl_event.ProgressStart(
            worker_id='main', task_id='overall', total=total_tasks
        )
    )

    sink = ThreadedEventSink(dispatcher)
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
                    pl_event.ProgressAdvance(
                        worker_id='main', task_id='overall', completed=i
                    )
                )

        base.tasks_apply_results(cache, stream_results())

    dispatcher.dispatch(
        pl_event.ProgressCompleted(worker_id='main', task_id='overall')
    )
