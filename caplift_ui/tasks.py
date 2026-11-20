"""Worker-thread plumbing for Tkinter.

Tk widgets may only be touched from the thread that created them. Every CLI call
therefore runs on a worker thread and reports back through a queue that the UI
drains on the main thread with ``after()``. Nothing in this module touches a
widget off the main thread.
"""
from __future__ import annotations

import queue
import sys
import threading
import traceback
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

POLL_INTERVAL_MS = 60

Work = Callable[[], Any]
OnSuccess = Callable[[Any], None]
OnError = Callable[[BaseException], None]


@dataclass
class Task:
    """One unit of background work plus its result and callbacks."""

    work: Work
    on_success: Optional[OnSuccess] = None
    on_error: Optional[OnError] = None
    label: str = ""
    value: Any = None
    error: Optional[BaseException] = None
    traceback_text: str = ""

    @property
    def failed(self) -> bool:
        return self.error is not None


class TaskBus:
    """Runs callables off the UI thread and delivers results on it.

    ``submit`` never blocks. For each task exactly one of ``on_success`` or
    ``on_error`` fires, on the main thread. ``on_busy_change`` is also called on
    the main thread whenever the number of in-flight tasks changes.
    """

    def __init__(
        self,
        widget: Any,
        on_busy_change: Optional[Callable[[int], None]] = None,
    ) -> None:
        self._widget = widget
        self._queue: "queue.Queue[Task]" = queue.Queue()
        self._lock = threading.Lock()
        self._pending = 0
        self._on_busy_change = on_busy_change
        self._polling = False
        self._last_reported_pending = 0

    # ---- public API ----------------------------------------------------

    @property
    def pending(self) -> int:
        with self._lock:
            return self._pending

    @property
    def busy(self) -> bool:
        return self.pending > 0

    def submit(
        self,
        work: Work,
        on_success: Optional[OnSuccess] = None,
        on_error: Optional[OnError] = None,
        label: str = "",
    ) -> None:
        """Queue ``work`` for a worker thread."""
        task = Task(work=work, on_success=on_success, on_error=on_error, label=label)
        with self._lock:
            self._pending += 1
        threading.Thread(target=self._run, args=(task,), daemon=True).start()
        self._ensure_polling()

    # ---- worker side ---------------------------------------------------

    def _run(self, task: Task) -> None:
        try:
            task.value = task.work()
        except BaseException as exc:  # noqa: BLE001 - surfaced to the UI verbatim
            task.error = exc
            task.traceback_text = traceback.format_exc()
        finally:
            # Queue the result BEFORE decrementing _pending. _drain stops polling
            # as soon as pending hits zero, so decrementing first leaves a window
            # where a finished task sits in the queue with nobody scheduled to
            # drain it — its callbacks would never fire.
            self._queue.put(task)
            with self._lock:
                self._pending -= 1

    # ---- main-thread side ----------------------------------------------

    def _ensure_polling(self) -> None:
        if not self._polling:
            self._polling = True
            self._widget.after(POLL_INTERVAL_MS, self._drain)

    def _drain(self) -> None:
        while True:
            try:
                task = self._queue.get_nowait()
            except queue.Empty:
                break
            # Guarded: an exception escaping here would skip the reschedule at
            # the end of this method, leaving _polling True forever and stalling
            # the bus so every later submit silently does nothing.
            try:
                self._dispatch(task)
            except BaseException:  # noqa: BLE001 - one bad callback must not win
                self._report_callback_failure()

        self._report_busy()

        if self.pending == 0 and self._queue.empty():
            self._polling = False
            return
        self._widget.after(POLL_INTERVAL_MS, self._drain)

    def _report_callback_failure(self) -> None:
        """Route a callback crash to the app's handler instead of killing the loop."""
        exc_type, exc_value, exc_traceback = sys.exc_info()
        handler = getattr(self._widget, "report_callback_exception", None)
        if callable(handler):
            handler(exc_type, exc_value, exc_traceback)
            return
        traceback.print_exception(exc_type, exc_value, exc_traceback)  # pragma: no cover

    def _dispatch(self, task: Task) -> None:
        if task.failed:
            if task.on_error is not None:
                task.on_error(task.error)  # type: ignore[arg-type]
            return
        if task.on_success is not None:
            task.on_success(task.value)

    def _report_busy(self) -> None:
        current = self.pending
        if current == self._last_reported_pending:
            return
        self._last_reported_pending = current
        if self._on_busy_change is not None:
            try:
                self._on_busy_change(current)
            except Exception:  # pragma: no cover - never let UI glue crash the loop
                pass


def describe_exception(exc: BaseException) -> str:
    """One-line, user-facing description of a failure."""
    from .cli_runner import CliCommandError, CliNotFoundError, CliTimeoutError
    from .parser import describe_cli_error

    if isinstance(exc, CliNotFoundError):
        return str(exc)
    if isinstance(exc, CliTimeoutError):
        return str(exc)
    if isinstance(exc, CliCommandError):
        return describe_cli_error(exc.result.stderr, exc.result.stdout)
    if isinstance(exc, (FileNotFoundError, PermissionError, OSError)):
        return str(exc)
    message = str(exc).strip()
    return message or exc.__class__.__name__


def exception_details(exc: BaseException, traceback_text: str = "") -> List[str]:
    """Lines for the log console: summary plus traceback when available."""
    lines = [f"{exc.__class__.__name__}: {exc}"]
    if traceback_text:
        lines.append(traceback_text.rstrip())
    return lines
