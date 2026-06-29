"""Task's execution context."""

from dataclasses import dataclass

from clunkster.pipeline.events.sink import EventSink


@dataclass(slots=True)
class ExecutionContext:
    """Unified execution context for tasks sent over IPC."""

    sink: EventSink
