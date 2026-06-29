"""Multiprocessing executor."""

import collections.abc as col
import concurrent.futures
import multiprocessing as mp
import os
import threading
from dataclasses import replace
from types import TracebackType
from typing import cast, override

from clunkster.pipeline.cache import FileBuildCache
from clunkster.pipeline.events import context as pl_context
from clunkster.pipeline.events import dispatcher as pl_dispatcher
from clunkster.pipeline.events import event as pl_event
from clunkster.pipeline.events import sink as pl_sink
from clunkster.pipeline.executor import base
from clunkster.pipeline.executor.base import ExecuteTaskResult
from clunkster.pipeline.task import Task


class QueueEventSink(pl_sink.EventSink):
    """Event sink that funnels events into ``multiprocessing.Queue``."""

    def __init__(
        self,
        queue: mp.Queue[pl_event.Event | None],
    ) -> None:
        """Initialize the sink with the queue."""
        self._queue = queue

    @override
    def emit(self, event: pl_event.Event) -> None:
        """Emit an event.

        Dynamically replaces event's worker id with current process id.
        """
        worker_event = replace(event, worker_id=str(os.getpid()))
        self._queue.put(worker_event)


class QueueEventReceiver:
    """Queue event receiver.

    Receive events from ``multiprocessing.Queue`` and feed them into the
    given dispatcher.

    Starts a separate polling thread.
    """

    def __init__(
        self,
        queue: mp.Queue[pl_event.Event | None],
        dispatcher: pl_dispatcher.EventDispatcher,
    ) -> None:
        """Initialize the receiver with the given queue.

        :param queue: Queue to receive events from.
        :param dispatcher: Dispatcher to funnel events into.
        """
        self._queue = queue
        self._dispatcher = dispatcher

        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
        )

    def start(self) -> None:
        """Start polling thread."""
        self._thread.start()

    def stop(self) -> None:
        """Push stop message into queue and wait for the thread to finish."""
        self._queue.put(None)
        self._thread.join()

    def _run(self) -> None:
        """Polling loop.

        Stops when queue receives None.
        """
        while True:
            event = self._queue.get()
            if event is None:
                break

            self._dispatcher.dispatch(event)

    def __enter__(self) -> QueueEventReceiver:
        """Context manager enter."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit."""
        self.stop()


def execute_mp(
    tasks: col.Sequence[Task],
    cache: FileBuildCache,
    dispatcher: pl_dispatcher.EventDispatcher,
    *,
    max_workers: int | None = None,
) -> None:
    """Execute given tasks with multiprocessing executor.

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

    manager = mp.Manager()
    queue: mp.Queue[pl_event.Event | None] = cast(
        mp.Queue[pl_event.Event | None], manager.Queue()
    )

    with QueueEventReceiver(queue, dispatcher):
        sink = QueueEventSink(queue)
        ctx = pl_context.ExecutionContext(sink)

        with concurrent.futures.ProcessPoolExecutor(
            max_workers=max_workers
        ) as executor:
            futures = {
                executor.submit(base.task_exec, task, ctx): task
                for task in tasks
            }

            def stream_results() -> col.Iterator[
                tuple[Task, ExecuteTaskResult]
            ]:
                for i, f in enumerate(
                    concurrent.futures.as_completed(futures), start=1
                ):
                    yield futures[f], f.result()
                    dispatcher.dispatch(
                        pl_event.ProgressAdvance(
                            worker_id='main', task_id='overall', completed=i
                        )
                    )

            base.tasks_apply_results(cache, stream_results())

        dispatcher.dispatch(
            pl_event.ProgressCompleted(worker_id='main', task_id='overall')
        )
