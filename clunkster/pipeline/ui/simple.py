"""Simple print-based Ui."""

import threading
from typing import override

from clunkster.pipeline.events import event
from clunkster.pipeline.ui.base import Ui


class UiSimple(Ui):
    """Simple print-based Ui."""

    @override
    def __init__(self, step_name: str, _: int) -> None:
        """Initialize the Ui object."""
        self.step_name = step_name

        self.task_id = '...'
        self.total = 1
        self.last_pct_printed = -1

    @override
    def on_task_started(self, e: event.TaskStarted) -> None:
        self.task_id = e.task_id
        self.last_pct_printed = -1
        print(f'--- [ {self.step_name} | Task: {self.task_id} ] ---')

    @override
    def on_progress_start(self, e: event.ProgressStart) -> None:
        self.total = max(1, e.total)
        self.last_pct_printed = 0

    @override
    def on_progress_advance(self, e: event.ProgressAdvance) -> None:
        pct = int((e.completed / self.total) * 100)
        if pct % 25 == 0 and pct != self.last_pct_printed:
            print(f'[{self.task_id}] Progress: {pct}%')
            self.last_pct_printed = pct

    @override
    def on_status(self, e: event.Status) -> None:
        print(f'  | {e.text}')

    @override
    def on_task_finished(self, e: event.TaskFinished) -> None:
        status = 'DONE' if e.success else 'FAILED'
        print(f'[{self.task_id}] {status}')

    @override
    def start(self) -> None:
        print(f'\n=== {self.step_name} ===')

    @override
    def stop(self) -> None:
        pass


class UiSimpleAsync(Ui):
    """Simple print-based Ui. Async version."""

    @override
    def __init__(self, step_name: str, width: int = 120) -> None:
        """Initialize the Ui object."""
        self.step_name = step_name

        self.total_target = 1
        self.last_pct_printed = -1

        self._lock = threading.Lock()

    def update_total_progress(self, current: int, total: int) -> None:
        """Called by main thread to update the overall step progress."""
        with self._lock:
            self.total_target = max(1, total)
            pct = int((current / self.total_target) * 100)

            if pct % 20 == 0 and pct != self.last_pct_printed:
                print(f'[{self.step_name}]: {pct}% ({current}/{total})')
                self.last_pct_printed = pct

    @override
    def on_task_started(self, e: event.TaskStarted) -> None:
        with self._lock:
            print(f'  -> [{e.worker_id}] Started: {e.task_id}')

    @override
    def on_task_finished(self, e: event.TaskFinished) -> None:
        with self._lock:
            status = 'DONE' if e.success else 'FAILED'
            if e.success:
                print(f'  <- [{e.worker_id}] Finished: {e.task_id}')
            else:
                print(f'  !> [{e.worker_id}] {status}: {e.task_id}')

    @override
    def start(self) -> None:
        print(f'\n=== {self.step_name} ===')

    @override
    def stop(self) -> None:
        print(f'=== {self.step_name} ===\n')
