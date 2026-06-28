from clunkster.pipeline.ui.base import Ui
from typing import override
from clunkster.pipeline.events import event
from clunkster.pipeline.events.dispatcher import EventDispatcher
import threading


class UiSimple(Ui):
    @override
    def __init__(self, step_name: str, width: int = 60) -> None:
        self.step_name = step_name

        self.task_id = "..."
        self.total = 1
        self.last_pct_printed = -1

    @override
    def register(self, dispatcher: EventDispatcher):
        dispatcher.clear()
        dispatcher.register(event.TaskStarted, self.on_task_started)
        dispatcher.register(event.ProgressStart, self.on_progress_start)
        dispatcher.register(event.ProgressAdvance, self.on_progress_advance)
        dispatcher.register(event.Status, self.on_status)
        dispatcher.register(event.TaskFinished, self.on_task_finished)

    def on_task_started(self, e: event.TaskStarted):
        self.task_id = e.task_id
        self.last_pct_printed = -1
        print(f"--- [ {self.step_name} | Task: {self.task_id} ] ---")

    def on_progress_start(self, e: event.ProgressStart):
        self.total = max(1, e.total)
        self.last_pct_printed = 0

    def on_progress_advance(self, e: event.ProgressAdvance):
        pct = int((e.completed / self.total) * 100)
        if pct % 25 == 0 and pct != self.last_pct_printed:
            print(f"[{self.task_id}] Progress: {pct}%")
            self.last_pct_printed = pct

    def on_status(self, e: event.Status):
        print(f"  | {e.text}")

    def on_task_finished(self, e: event.TaskFinished):
        status = "DONE" if e.success else "FAILED"
        print(f"[{self.task_id}] {status}")

    @override
    def start(self):
        print(f"\n=== {self.step_name} ===")

    @override
    def stop(self):
        pass


class UiSimpleAsync(Ui):
    @override
    def __init__(self, step_name: str, width: int = 120):
        self.step_name = step_name

        self.total_target = 1
        self.last_pct_printed = -1

        self._lock = threading.Lock()

    def update_total_progress(self, current: int, total: int):
        """Called by main thread to update the overall step progress."""
        with self._lock:
            self.total_target = max(1, total)
            pct = int((current / self.total_target) * 100)

            if pct % 20 == 0 and pct != self.last_pct_printed:
                print(f"[{self.step_name}]: {pct}% ({current}/{total})")
                self.last_pct_printed = pct

    @override
    def register(self, dispatcher: EventDispatcher):
        dispatcher.register(event.TaskStarted, self.on_task_started)
        dispatcher.register(event.TaskFinished, self.on_task_finished)

    def on_task_started(self, e: event.TaskStarted):
        with self._lock:
            print(f"  -> [{e.worker_id}] Started: {e.task_id}")

    def on_task_finished(self, e: event.TaskFinished):
        with self._lock:
            status = "DONE" if e.success else "FAILED"
            if e.success:
                print(f"  <- [{e.worker_id}] Finished: {e.task_id}")
            else:
                print(f"  !> [{e.worker_id}] {status}: {e.task_id}")

    @override
    def start(self):
        print(f"\n=== {self.step_name} ===")

    @override
    def stop(self):
        print(f"=== {self.step_name} ===\n")
