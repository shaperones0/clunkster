"""Event dispatcher."""

from collections.abc import Callable
from typing import cast

from clunkster.pipeline.events.event import Event


class EventDispatcher:
    """Event dispatcher.

    Allows registering dispatchers by event type.
    """

    def __init__(self) -> None:
        """Initialize event dispatcher.

        Initializes internal ``handlers`` dictionary.
        """
        self._handlers: dict[type[Event], list[Callable[[Event], None]]] = {}

    def clear(self) -> None:
        """Clear internal handlers."""
        self._handlers.clear()

    def register[TEvent: Event](
        self,
        event_type: type[TEvent],
        handler: Callable[[TEvent], None],
    ) -> None:
        """Register a handler for the given event type."""
        self._handlers.setdefault(event_type, []).append(
            cast(Callable[[Event], None], handler)
        )

    def dispatch(self, event: Event) -> None:
        """Dispatch an event."""
        for cls in type(event).__mro__:
            for handler in self._handlers.get(cls, ()):
                handler(event)
