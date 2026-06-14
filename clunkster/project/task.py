"""Processing pipeline backbone."""

import collections.abc as col
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from clunkster.project.cache import file_hash


class Task(ABC):
    """Base class for project processing tasks."""

    def __init__(
        self,
        task_id: str,
        inputs: col.Iterable[Path],
        outputs: col.Iterable[Path],
    ) -> None:
        """Initialize processing task.

        The task is skipped all output files exist, and input hashes match
        recorded hashes.
        :param task_id: Task ID.
        :param inputs: Input files (used in hashes).
        :param outputs: Output files (checked existence).
        """
        self.task_id = task_id
        self.inputs = list(inputs)
        self.outputs = list(outputs)

    def get_input_hash(self) -> str:
        """Calculate MD5 hash of all input files."""
        return file_hash(*self.inputs)

    @abstractmethod
    def execute(self) -> None:
        """Specific processing logic."""


@dataclass(frozen=True, slots=True)
class ExecuteTaskResult:
    """Result of task execution."""

    task_id: str
    new_hash: str
    success: bool
    error: str


def worker_exec_task(task: Task) -> ExecuteTaskResult:
    """Execute the task in mp-friendly way and return task result.

    :param task: Task to execute.
    :return: Task result.
    """
    hsh = task.get_input_hash()
    try:
        # ensure output directories exist
        for out in task.outputs:
            out.parent.mkdir(parents=True, exist_ok=True)

        task.execute()

        return ExecuteTaskResult(
            task_id=task.task_id,
            new_hash=hsh,
            success=True,
            error='',
        )

    except Exception as err:  # noqa: BLE001
        return ExecuteTaskResult(
            task_id=task.task_id,
            new_hash=hsh,
            success=False,
            error=str(err),
        )
