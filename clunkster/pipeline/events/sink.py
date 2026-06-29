"""Event sink.

Event sinks are used by workers as a place to post messages without
being concerned for any communication issues.
"""

import threading
from abc import abstractmethod
from dataclasses import replace
from typing import Protocol, override

from clunkster.pipeline.events.dispatcher import EventDispatcher
from clunkster.pipeline.events.event import Event


class EventSink(Protocol):
    """Abstract event sink."""

    @abstractmethod
    def emit(self, event: Event) -> None:
        """Emit an event."""


class NullEventSink(EventSink):
    """Null event sink.

    Voids all given events.
    """

    @override
    def emit(self, event: Event) -> None:
        pass


class DispatchEventSink(EventSink):
    """Dispatch event sink.

    Passthrough events into given dispatcher. Intended for sync operations.
    """

    def __init__(self, dispatcher: EventDispatcher) -> None:
        """Initialize sink with given dispatcher."""
        self._dispatcher = dispatcher

    @override
    def emit(self, event: Event) -> None:
        self._dispatcher.dispatch(event)


class DirectEventSink(DispatchEventSink):
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
    def emit(self, event: Event) -> None:
        worker_id = threading.current_thread().name
        worker_event = replace(event, worker_id=worker_id)
        with self._lock:
            self._dispatcher.dispatch(worker_event)
