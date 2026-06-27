from dataclasses import dataclass

from clunkster.project.task import Task



@dataclass(frozen=True, slots=True)
class ExecuteTaskResult:
    """Result of task execution."""

    task_id: str
    success: bool
    error: str


def worker_exec_task(task: Task) -> ExecuteTaskResult:
    """Execute the task in mp-friendly way and return task result.

    :param task: Task to execute.
    :return: Task result.
    """
    try:
        # ensure output directories exist
        for out in task.outputs:
            out.parent.mkdir(parents=True, exist_ok=True)

        task.execute()

        return ExecuteTaskResult(
            task_id=task.task_id,
            success=True,
            error='',
        )

    except Exception as err:  # noqa: BLE001
        return ExecuteTaskResult(
            task_id=task.task_id,
            success=False,
            error=str(err),
        )
