import collections.abc as col
import concurrent.futures
import multiprocessing as mp
import threading
from dataclasses import replace
from types import TracebackType
from typing import override
import os

from clunkster.pipeline.events import context as proj_context, dispatcher as proj_dispatcher, event as proj_event, sink as proj_sink
from clunkster.pipeline.task import Task
from clunkster.pipeline.executor import base
from clunkster.pipeline.cache import FileBuildCache



class QueueEventSink(proj_sink.EventSink):

    def __init__(
        self,
        queue: mp.Queue[proj_event.Event | None],
    ):
        self._queue = queue

    @override
    def emit(self, event: proj_event.Event) -> None:
        worker_event = replace(event, worker_id=str(os.getpid()))
        self._queue.put(worker_event)


class QueueEventReceiver:

    def __init__(self, queue: mp.Queue[proj_event.Event | None], dispatcher: proj_dispatcher.EventDispatcher) -> None:
        self._queue = queue
        self._dispatcher = dispatcher

        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._queue.put(None)
        self._thread.join()

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            if event is None:
                break

            self._dispatcher.dispatch(event)

    def __enter__(self) -> QueueEventReceiver:
        self.start()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        self.stop()


def execute_mp(
    tasks: col.Iterable[Task],
    cache: FileBuildCache,
    dispatcher: proj_dispatcher.EventDispatcher,
    *,
    max_workers: int | None = None,
) -> None:
    tasks, cached = base.tasks_filter_stale(tasks, cache)
    if not tasks:
        return

    manager = mp.Manager()
    queue = manager.Queue()

    with QueueEventReceiver(queue, dispatcher):
        sink = QueueEventSink(queue)
        ctx = proj_context.ExecutionContext(sink)

        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(base.task_exec, task, ctx): task
                for task in tasks
            }

            results = (
                (futures[f], f.result())
                for f in concurrent.futures.as_completed(futures)
            )

            base.tasks_apply_results(cache, results)
