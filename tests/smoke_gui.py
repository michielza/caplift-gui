"""Manual GUI smoke test.

Builds the real window, drives it through a timed sequence, optionally saves a
screenshot, then exits. Not collected by unittest (the filename is not
``test_*``) because it needs a desktop session.

Everything is scheduled with ``after`` and then ``mainloop()`` runs: a modal
dialog opens its own nested event loop, so manually pumping Tk (``update()`` in
a sleep loop) deadlocks. Scheduling keeps every step inside whichever loop is
active.

Usage:
    python tests/smoke_gui.py                                  # open for 6s
    python tests/smoke_gui.py --seconds 10 --shot out.png
    python tests/smoke_gui.py --view wrapped --select-first --shot wrapped.png
    python tests/smoke_gui.py --base meta/muse-glimmer --preview --shot preview.png
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description="Caplift UI smoke test")
    parser.add_argument("--seconds", type=float, default=6.0, help="total runtime before exiting")
    parser.add_argument("--shot", type=str, default="", help="path to write a screenshot")
    parser.add_argument("--view", type=str, default="", help="switch to this view, e.g. wrapped")
    parser.add_argument(
        "--select-first",
        action="store_true",
        help="select the first table row so the detail panel is populated",
    )
    parser.add_argument(
        "--base",
        type=str,
        default="",
        help="base template to fill in before acting, e.g. meta/muse-glimmer",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="trigger a dry run on the selection and show the preview dialog",
    )
    args = parser.parse_args()

    import tkinter as tk

    from caplift_ui.config import load_config
    from caplift_ui.ui.app import App

    config = load_config()
    # Force a sane on-screen size regardless of any saved geometry.
    config.window.width = 1240
    config.window.height = 800
    config.window.x = 60
    config.window.y = 60

    app = App(config)
    app.attributes("-topmost", True)
    app.lift()

    def close_dialogs() -> None:
        """Release nested event loops so the process can exit."""
        for child in list(app.winfo_children()):
            if isinstance(child, tk.Toplevel):
                try:
                    child.grab_release()
                except Exception:  # pragma: no cover - best effort
                    pass
                child.destroy()

    def take_shot() -> None:
        if not args.shot:
            return
        from PIL import ImageGrab

        app.update_idletasks()
        has_dialog = any(isinstance(child, tk.Toplevel) for child in app.winfo_children())
        if has_dialog:
            # A dialog can extend beyond the app's rectangle, and the app is
            # forced on top here, so capture the whole screen.
            image = ImageGrab.grab()
        else:
            x, y = app.winfo_rootx(), app.winfo_rooty()
            w, h = app.winfo_width(), app.winfo_height()
            image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        image.save(args.shot)
        print(f"screenshot saved: {args.shot} ({image.width}x{image.height})")

    def current_view():
        return app.current_view()

    def do_view() -> None:
        if args.view:
            app.show_view(args.view)

    def do_select() -> None:
        if not args.select_first:
            return
        table = getattr(current_view(), "table", None)
        if table is not None:
            table.select_first()

    def do_base() -> None:
        if not args.base:
            return
        field = getattr(current_view(), "base_field", None)
        if field is not None:
            field.set(args.base)
            print(f"base template set to {args.base}")

    def do_preview() -> None:
        if not args.preview:
            return
        view = current_view()
        preview = getattr(view, "preview_selected", None)
        if callable(preview):
            preview()

    def finish() -> None:
        # Capture before closing: a modal dialog is part of what we want to see.
        take_shot()
        close_dialogs()
        print("smoke test finished without an unhandled exception")
        app.after(250, app.destroy)

    # Proportional timeline: give startup refreshes time to land before acting.
    total_ms = int(max(2.0, args.seconds) * 1000)
    schedule = (
        (0.30, do_view),
        (0.36, do_select),
        (0.42, do_base),
        (0.48, do_preview),
        (0.88, finish),
    )
    for fraction, callback in schedule:
        app.after(int(total_ms * fraction), callback)

    # A crash inside a Tk callback is otherwise swallowed; surface it loudly.
    crashed: list = []
    original_handler = app.report_callback_exception

    def loud_handler(exc_type, exc_value, exc_traceback) -> None:
        crashed.append(exc_value)
        print(f"UNHANDLED UI EXCEPTION: {exc_type.__name__}: {exc_value}", file=sys.stderr)
        original_handler(exc_type, exc_value, exc_traceback)

    app.report_callback_exception = loud_handler

    started = time.monotonic()
    app.mainloop()
    elapsed = time.monotonic() - started

    if crashed:
        print(f"FAILED: {len(crashed)} unhandled exception(s)", file=sys.stderr)
        return 1
    print(f"exited cleanly after {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
