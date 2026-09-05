"""UI abstraction."""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self

from clunkster.pipeline.events import event
from clunkster.pipeline.events.dispatcher import EventDispatcher


class Ui(ABC):
    """Abstract UI."""

    @abstractmethod
    def __init__(self, step_name: str, width: int = 60) -> None:
        """Initialize the Ui class.

        :param step_name: Current step name.
        :param width: UI width.
        """

    def register(self, dispatcher: EventDispatcher) -> None:
        """Register a dispatcher for using this UI abstraction.

        :param dispatcher: Dispatcher object.
        """
        dispatcher.clear()
        dispatcher.register(event.TaskStarted, self.on_task_started)
        dispatcher.register(event.TaskFinished, self.on_task_finished)
        dispatcher.register(event.ProgressStart, self.on_progress_start)
        dispatcher.register(event.ProgressAdvance, self.on_progress_advance)
        dispatcher.register(
            event.ProgressCompleted, self.on_progress_completed
        )
        dispatcher.register(event.Status, self.on_status)

    @abstractmethod
    def start(self) -> None:
        """Start a pipeline step."""

    @abstractmethod
    def stop(self) -> None:
        """End a pipeline step."""

    def __enter__(self) -> Self:
        """Context manager enter."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit."""
        self.stop()

    def on_task_started(self, e: event.TaskStarted) -> None:  # ruff: ignore[empty-method-without-abstract-decorator]
        """TaskStarted event handler."""

    def on_task_finished(self, e: event.TaskFinished) -> None:  # ruff: ignore[empty-method-without-abstract-decorator]
        """TaskFinished event handler."""

    def on_progress_start(self, e: event.ProgressStart) -> None:  # ruff: ignore[empty-method-without-abstract-decorator]
        """ProgressStart event handler."""

    def on_progress_advance(self, e: event.ProgressAdvance) -> None:  # ruff: ignore[empty-method-without-abstract-decorator]
        """ProgressAdvance event handler."""

    def on_progress_completed(self, e: event.ProgressCompleted) -> None:  # ruff: ignore[empty-method-without-abstract-decorator]
        """ProgressCompleted event handler."""

    def on_status(self, e: event.Status) -> None:  # ruff: ignore[empty-method-without-abstract-decorator]
        """Status event handler."""


class UiAsync(Ui, ABC):
    """Async UI abstraction.

    Contains method for setting total progress.
    """

    @abstractmethod
    def update_total_progress(self, current: int, total: int) -> None:
        """Update total progress on the main thread.

        :param current: Number of processes items.
        :param total: Total number of items.
        """
