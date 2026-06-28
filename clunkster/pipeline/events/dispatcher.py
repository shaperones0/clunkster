from collections.abc import Callable
from typing import cast

from clunkster.pipeline.events.event import Event


class EventDispatcher:

    def __init__(self):
        self._handlers: dict[type[Event], list[Callable[[Event], None]]] = {}

    def clear(self) -> None:
        self._handlers.clear()

    def register[TEvent: Event](
        self,
        event_type: type[TEvent],
        handler: Callable[[TEvent], None],
    ) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def dispatch(self, event: Event) -> None:
        for cls in type(event).__mro__:
            for handler in self._handlers.get(cls, ()):
                handler(event)
