from abc import abstractmethod
from typing import Protocol, override
from dataclasses import replace
import os
import threading

from clunkster.pipeline.events.event import Event
from clunkster.pipeline.events.dispatcher import EventDispatcher


class EventSink(Protocol):
    @abstractmethod
    def emit(self, event: Event) -> None: ...


class NullEventSink(EventSink):
    @override
    def emit(self, event: Event) -> None:
        pass


class DispatchEventSink(EventSink):

    def __init__(self, dispatcher: EventDispatcher) -> None:
        self._dispatcher = dispatcher

    @override
    def emit(self, event: Event) -> None:
        self._dispatcher.dispatch(event)


class DirectEventSink(DispatchEventSink):
    @override
    def __init__(self, dispatcher: EventDispatcher) -> None:
        super().__init__(dispatcher)
        self._lock = threading.Lock()

    @override
    def emit(self, event: Event) -> None:
        worker_id = threading.current_thread().name
        worker_event = replace(event, worker_id=worker_id)
        with self._lock:
            self._dispatcher.dispatch(worker_event)

