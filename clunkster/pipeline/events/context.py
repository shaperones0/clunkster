from dataclasses import dataclass

from clunkster.pipeline.events.sink import EventSink


@dataclass(slots=True)
class ExecutionContext:
    sink: EventSink
