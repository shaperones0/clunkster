"""Event sink.

Event sinks are used by workers as a place to post messages concerning
themselves about communication intricacies.
"""

from abc import abstractmethod
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
