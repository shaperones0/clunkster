from clunkster.pipeline.events.sink import EventSink
from clunkster.pipeline.events import event
from clunkster.pipeline.events.dispatcher import EventDispatcher
from typing import Any
import collections.abc as col
from clunkster.pipeline.ui.base import Ui
import functools as ft
from clunkster.pipeline.events.sink import DispatchEventSink


class SinkAdapter:
    def __init__(self, sink: EventSink, step_name: str) -> None:
        self.sink = sink
        self.step_name = step_name

    def out(self, *messages: Any, sep: str = ' ') -> None:
        formatted = sep.join(str(message) for message in messages)
        self.sink.emit(event.Status(text=formatted))

    def progress[TItem](self, seq: col.Sequence[TItem]) -> col.Iterator[TItem]:
        ln = len(seq)
        freq = max(1, ln // 1000)
        self.sink.emit(event.ProgressStart(task_id=self.step_name, total=ln))
        for idx, elem in enumerate(seq, start=1):
            yield elem
            if idx % freq == 0:
                self.sink.emit(event.ProgressAdvance(task_id=self.step_name, completed=idx))
        self.sink.emit(event.ProgressCompleted(task_id=self.step_name))


ADAPTER: SinkAdapter | None = None


def ui_auto_sink[**P, R](cls_ui: type[Ui], step_name: str, *, width: int | None = None, cls_sink: type[DispatchEventSink] = DispatchEventSink) -> col.Callable[
    [col.Callable[P, R]],
    col.Callable[P, R]
]:
    def decorator(func: col.Callable[P, R]) -> col.Callable[P, R]:
        @ft.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            global ADAPTER
            if width is None:
                ui = cls_ui(step_name=step_name)
            else:
                ui = cls_ui(step_name=step_name, width=width)
            dispatcher = EventDispatcher()
            ui.register(dispatcher)
            sink = cls_sink(dispatcher)
            ADAPTER = SinkAdapter(sink, step_name)

            with ui:
                sink.emit(event.TaskStarted(task_id=step_name))
                ret = func(*args, **kwargs)
                sink.emit(event.TaskFinished(task_id=step_name, success=True))

            ADAPTER = None
            return ret
        return wrapper
    return decorator


def ui_out(*messages: Any, sep: str = ' ') -> None:
    assert ADAPTER is not None
    ADAPTER.out(*messages, sep=sep)


def ui_progress[TItem](seq: col.Sequence[TItem]) -> col.Iterator[TItem]:
    assert ADAPTER is not None
    return ADAPTER.progress(seq)
