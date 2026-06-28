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


class DirectEventSink(EventSink):

    def __init__(self, dispatcher: EventDispatcher) -> None:
        self._dispatcher = dispatcher
        self._lock = threading.Lock()

    @override
    def emit(self, event: Event) -> None:
        worker_event = replace(event, worker_id=f'worker_{os.getpid()}')
        with self._lock:
            self._dispatcher.dispatch(worker_event)

