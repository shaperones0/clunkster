from abc import ABC
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class Event(ABC):
    """Base class for all events."""
    worker_id: str = "main"


@dataclass(frozen=True, slots=True)
class TaskStarted(Event):
    task_id: str


@dataclass(frozen=True, slots=True)
class TaskFinished(Event):
    task_id: str
    success: bool


@dataclass(frozen=True, slots=True)
class Progress(Event):
    task_id: str
    completed: int
    total: int


@dataclass(frozen=True, slots=True)
class Status(Event):
    text: str
