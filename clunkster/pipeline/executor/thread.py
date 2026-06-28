import collections.abc as col
import concurrent.futures

from clunkster.pipeline.events.context import ExecutionContext
from clunkster.pipeline.task import Task
from clunkster.pipeline.executor import base
from clunkster.pipeline.cache import FileBuildCache
from clunkster.pipeline.events.dispatcher import EventDispatcher
from clunkster.pipeline.events.sink import DirectEventSink


def execute_threaded(
    tasks: col.Iterable[Task],
    cache: FileBuildCache,
    dispatcher: EventDispatcher,
    *,
    max_workers: int | None = None,
) -> None:
    tasks, cached = base.tasks_filter_stale(tasks, cache)
    if not tasks:
        return

    sink = DirectEventSink(dispatcher)
    ctx = ExecutionContext(
        sink=sink
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(base.task_exec, task, ctx): task
            for task in tasks
        }

        results = (
            (futures[f], f.result())
            for f in concurrent.futures.as_completed(futures)
        )

        base.tasks_apply_results(cache, results)
