"""Sink adapter for ease of use."""

import collections.abc as col
import functools as ft

from clunkster.pipeline.events import event
from clunkster.pipeline.events.dispatcher import EventDispatcher
from clunkster.pipeline.events.sink import DispatchEventSink, EventSink
from clunkster.pipeline.ui.base import Ui
from clunkster.pipeline.ui.simple import UiSimple


class SinkAdapter:
    """Sink adapter for ease of use."""

    def __init__(self, sink: EventSink, step_name: str) -> None:
        """Initialize the sink adapter.

        :param sink: Sink to funnel messages in.
        :param step_name: Current step name for ``task_id``.
        """
        self.sink = sink
        self.step_name = step_name

    def out(self, *messages: object, sep: str = ' ') -> None:
        """Output a message as a ``Status`` event."""
        formatted = sep.join(str(message) for message in messages)
        self.sink.emit(event.Status(text=formatted))

    def progress[TItem](self, seq: col.Sequence[TItem]) -> col.Iterator[TItem]:
        """Wrap a sequence in a progress bar.

        :param seq: Input sequence.
        :return: Iterator over the sequence.
        """
        ln = len(seq)
        freq = max(1, ln // 1000)
        self.sink.emit(event.ProgressStart(task_id=self.step_name, total=ln))
        for idx, elem in enumerate(seq, start=1):
            yield elem
            if idx % freq == 0:
                self.sink.emit(
                    event.ProgressAdvance(
                        task_id=self.step_name, completed=idx
                    )
                )
        self.sink.emit(event.ProgressCompleted(task_id=self.step_name))


ADAPTER: SinkAdapter | None = None


def ui_auto_sink[**P, R](
    step_name: str,
    *,
    width: int | None = None,
    cls_ui: type[Ui] = UiSimple,
    cls_sink: type[DispatchEventSink] = DispatchEventSink,
) -> col.Callable[[col.Callable[P, R]], col.Callable[P, R]]:
    """Automatic adapter setup for given pipeline step function.

    :param cls_ui: UI class to use.
    :param step_name: Name of the pipeline step.
    :param width: UI width.
    :param cls_sink: Sink class to use. Defaults to ``DispatchEventSink``.
    :return:
    """

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


def _adapter_simple() -> SinkAdapter:
    """Create baseline sink adapter."""
    dispatcher = EventDispatcher()
    return SinkAdapter(
        sink=DispatchEventSink(dispatcher=dispatcher), step_name='main'
    )


def _adapter_ensure() -> SinkAdapter:
    """Ensure ``ADAPTER`` exists."""
    global ADAPTER

    if ADAPTER is None:
        raise ValueError('Adapter is not initialized')
    return ADAPTER


def ui_out(*messages: object, sep: str = ' ') -> None:
    """Output a message as a ``Status`` event."""
    _adapter_ensure().out(*messages, sep=sep)


def ui_progress[TItem](seq: col.Sequence[TItem]) -> col.Iterator[TItem]:
    """Wrap a sequence in a progress bar."""
    return _adapter_ensure().progress(seq)
