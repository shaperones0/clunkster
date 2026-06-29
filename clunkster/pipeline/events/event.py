"""Pipeline builtin events."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    """Base class for all events."""

    worker_id: str = 'main'


@dataclass(frozen=True, slots=True)
class TaskStarted(Event):
    """Task started event."""

    task_id: str


@dataclass(frozen=True, slots=True)
class TaskFinished(Event):
    """Task finished event."""

    task_id: str
    success: bool


@dataclass(frozen=True, slots=True)
class ProgressStart(Event):
    """Start a progress bar with given total number of entries."""

    task_id: str
    total: int


@dataclass(frozen=True, slots=True)
class ProgressAdvance(Event):
    """Set progress bar progress."""

    task_id: str
    completed: int


@dataclass(frozen=True, slots=True)
class ProgressCompleted(Event):
    """Finish this task's progress bar."""

    task_id: str


@dataclass(frozen=True, slots=True)
class Status(Event):
    """Post a status message."""

    text: str
