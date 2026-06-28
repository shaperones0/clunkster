from abc import ABC, abstractmethod
from typing import Self
from types import TracebackType

from clunkster.pipeline.events.dispatcher import EventDispatcher


class Ui(ABC):
    @abstractmethod
    def __init__(self, step_name: str, width: int = 60) -> None:
        ...

    @abstractmethod
    def register(self, dispatcher: EventDispatcher):
        ...

    @abstractmethod
    def start(self):
        ...

    @abstractmethod
    def stop(self):
        ...

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        self.stop()
