"""Entry point for Caplift UI.

Run from source with ``python main.py``, or build a single executable with
PyInstaller (see ``main.spec`` / ``build.bat``). Place the resulting
``caplift-ui.exe`` next to ``lmstudio-caplift.exe``.
"""
from __future__ import annotations

import sys
import traceback

MIN_PYTHON = (3, 9)


def _fatal(title: str, message: str, details: str = "") -> None:
    """Report a startup failure, using a dialog when no console is attached."""
    text = f"{message}\n\n{details}".strip() if details else message
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, text)
        root.destroy()
    except Exception:  # pragma: no cover - last resort
        print(f"{title}: {text}", file=sys.stderr)


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        _fatal(
            "Python too old",
            f"Caplift UI needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.",
            f"Running {sys.version.split()[0]}.",
        )
        return 1

    try:
        from caplift_ui.config import load_config
        from caplift_ui.ui.app import App
    except ImportError as exc:
        _fatal(
            "Missing dependency",
            "Caplift UI could not start because a dependency is missing.",
            f"{exc}\n\nInstall dependencies with:\n    pip install -r requirements.txt",
        )
        return 1

    try:
        warnings: list[str] = []
        config = load_config(warnings=warnings)
        app = App(config, startup_warnings=warnings)
        app.mainloop()
    except Exception as exc:  # noqa: BLE001 - top-level guard for a windowed app
        _fatal("Caplift UI crashed", str(exc), traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
