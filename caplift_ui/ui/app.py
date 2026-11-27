"""Main application window."""
from __future__ import annotations

import tkinter as tk
from typing import Dict, Optional, Sequence

import customtkinter as ctk

from ..config import AppConfig, APP_NAME, config_path, find_cli, save_config
from ..cli_runner import CliError, CliRunner
from ..models import RegistryView
from ..tasks import TaskBus, describe_exception
from .available_view import AvailableView
from .settings_view import SettingsView
from .theme import COLORS, FONTS, apply_base_theme, apply_ttk_theme
from .widgets import Console, StatusPill
from .wolf import WolfMark, draw_paw
from .wrapped_view import WrappedView

NAV_ITEMS = (
    ("available", "Available models"),
    ("wrapped", "Wrapped models"),
    ("settings", "Settings"),
)

# Distinct from None (meaning "no executable found"), so the very first status
# check always runs.
_UNRESOLVED = object()


class App(ctk.CTk):
    """The Caplift UI window.

    Owns the config, the shared output console, and the worker-thread bus. Views
    are built once and swapped in the content area, so adding a feature means
    adding a view and a NAV_ITEMS entry.
    """

    def __init__(
        self,
        config: AppConfig,
        startup_warnings: Sequence[str] = (),
    ) -> None:
        apply_base_theme()
        super().__init__(fg_color=COLORS["bg"])
        apply_ttk_theme(self)

        self.app_config = config or AppConfig()
        # Held until the console exists, then logged once. A settings file that
        # could not be read falls back to defaults, and the user needs to know
        # that happened rather than discover it via a missing CLI path.
        self._startup_warnings: tuple[str, ...] = tuple(startup_warnings)
        self._current_view: Optional[str] = None
        self._views: Dict[str, ctk.CTkFrame] = {}
        self._nav_buttons: Dict[str, ctk.CTkButton] = {}
        self._last_cli_resolution: object = _UNRESOLVED

        self.title(f"{APP_NAME} — LM Studio wrapper helper")
        self.minsize(1020, 660)
        self._apply_geometry()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.tasks = TaskBus(self, on_busy_change=self._on_busy_change)

        self._build_layout()
        self._bind_shortcuts()
        self.show_view("available")

        self.after(120, self._startup_refresh)

    # ---- public state used by views -------------------------------------

    def build_runner(self) -> CliRunner:
        """Create a runner from the current settings.

        Raises :class:`CliNotFoundError` when the executable is missing; callers
        route that through :meth:`report_error`.
        """
        return CliRunner.from_config(self.app_config)

    def save_config(self) -> Optional[str]:
        """Persist settings and report failures instead of raising."""
        self._capture_geometry()
        return save_config(self.app_config)

    def log(self, message: str, level: str = "info") -> None:
        self.console.append(message, level)

    def report_error(self, title: str, exc: BaseException) -> None:
        """Log a failure and tell the user what went wrong."""
        summary = describe_exception(exc)
        self.log(f"{title}: {summary}", "error")
        if isinstance(exc, CliError):
            result = getattr(exc, "result", None)
            if result is not None:
                self.log(f"$ {result.command_line}", "command")
                if result.stdout.strip():
                    self.log(result.stdout.strip(), "stdout")
                if result.stderr.strip():
                    self.log(result.stderr.strip(), "stderr")
        self.set_status(summary, "error")

    def run_task(self, work, on_success=None, on_error=None, label: str = "") -> None:
        """Run ``work`` off the UI thread, reporting unhandled errors to the UI."""
        def wrapped():
            return work()

        def failed(exc: BaseException) -> None:
            if on_error is not None:
                on_error(exc)
            else:
                self.report_error(label or "Command failed", exc)

        self.tasks.submit(wrapped, on_success=on_success, on_error=failed, label=label)
        if label:
            self.set_status(f"{label}…", "accent")

    def on_registry_loaded(self, registry: RegistryView) -> None:
        """Called by the available view after a successful full listing.

        The same payload carries the tracked wrappers, so the wrapped view is
        updated from it rather than issuing a second CLI call.
        """
        self.count_pill.set_state(
            f"{registry.available_count} available · {registry.wrapped_count} wrapped",
            "accent",
        )
        wrapped_view = self._views.get("wrapped")
        if isinstance(wrapped_view, WrappedView) and registry.wrapped_count:
            wrapped_view.set_wrapped(registry.wrapped)
        self.set_status("Ready.", "ok")

    def notify_wrappers_changed(self) -> None:
        """A wrap succeeded: refresh the registry-backed views."""
        wrapped_view = self._views.get("wrapped")
        if isinstance(wrapped_view, WrappedView):
            wrapped_view.refresh()

    def on_config_changed(self) -> None:
        """Settings were saved: refresh the executable status."""
        self._refresh_cli_status()

    def last_base_template(self) -> str:
        recent = self.app_config.recent_base_templates
        return recent[0] if recent else ""

    # ---- layout ----------------------------------------------------------

    def _apply_geometry(self) -> None:
        window = self.app_config.window
        width = max(1020, int(window.width or 1200))
        height = max(660, int(window.height or 780))
        if window.x is not None and window.y is not None:
            self.geometry(f"{width}x{height}+{int(window.x)}+{int(window.y)}")
        else:
            self.geometry(f"{width}x{height}")
            self._center_on_screen(width, height)

    def _center_on_screen(self, width: int, height: int) -> None:
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            x = max(0, (screen_w - width) // 2)
            y = max(0, (screen_h - height) // 3)
            self.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:  # pragma: no cover - cosmetic
            pass

    def _capture_geometry(self) -> None:
        try:
            if self.state() == "zoomed":
                return
            self.app_config.window.width = self.winfo_width()
            self.app_config.window.height = self.winfo_height()
            self.app_config.window.x = self.winfo_x()
            self.app_config.window.y = self.winfo_y()
        except Exception:  # pragma: no cover - cosmetic
            pass

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=0)

        self._build_sidebar()

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=(16, 16), pady=(16, 0))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.console = Console(self, height=132)
        self.console.grid(row=1, column=1, sticky="ew", padx=(16, 16), pady=(12, 0))

        self._build_status_bar()

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=0, width=214)
        # Rows 0 and 1 only: row 2 holds the full-width status bar, and spanning
        # into it would make the sidebar footer sit behind the status bar.
        sidebar.grid(row=0, column=0, rowspan=2, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(2, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 18))
        brand.grid_columnconfigure(1, weight=1)

        mark = WolfMark(brand, size=42, background=COLORS["surface"])
        mark.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 10))

        ctk.CTkLabel(
            brand,
            text="Caplift",
            font=FONTS.heading,
            text_color=COLORS["text"],
            anchor="w",
        ).grid(row=0, column=1, sticky="sw")
        ctk.CTkLabel(
            brand,
            text="LM Studio wrapper helper",
            font=FONTS.small,
            text_color=COLORS["text_dim"],
            anchor="w",
        ).grid(row=1, column=1, sticky="nw")

        nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=10)
        nav.grid_columnconfigure(0, weight=1)

        for index, (key, label) in enumerate(NAV_ITEMS):
            button = ctk.CTkButton(
                nav,
                text=label,
                anchor="w",
                height=38,
                corner_radius=8,
                font=FONTS.nav,
                fg_color="transparent",
                hover_color=COLORS["surface_hi"],
                text_color=COLORS["text_muted"],
                command=lambda view_key=key: self.show_view(view_key),
            )
            button.grid(row=index, column=0, sticky="ew", pady=2)
            self._nav_buttons[key] = button

        footer = ctk.CTkFrame(sidebar, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 16))
        footer.grid_columnconfigure(0, weight=1)

        self.cli_pill = StatusPill(footer, text="Checking executable…", tone="neutral")
        self.cli_pill.grid(row=0, column=0, sticky="ew")

        self.cli_path_label = ctk.CTkLabel(
            footer,
            text="",
            font=FONTS.small,
            text_color=COLORS["text_dim"],
            anchor="w",
            justify="left",
            wraplength=180,
        )
        self.cli_path_label.grid(row=1, column=0, sticky="ew", pady=(6, 0))

    def _build_status_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=0, height=34)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        bar.grid_columnconfigure(2, weight=1)

        paw = tk.Canvas(bar, width=18, height=18, highlightthickness=0, bd=0, bg=COLORS["surface"])
        draw_paw(paw, 9, 9, 15, color=COLORS["accent"])
        paw.grid(row=0, column=0, sticky="w", padx=(14, 6), pady=8)

        self.status_pill = StatusPill(bar, text="Ready.", tone="neutral")
        self.status_pill.grid(row=0, column=1, sticky="w")

        self.count_pill = StatusPill(bar, text="no data yet", tone="neutral")
        self.count_pill.grid(row=0, column=3, sticky="e", pady=6)

        self.progress = ctk.CTkProgressBar(
            bar,
            mode="indeterminate",
            width=110,
            height=6,
            corner_radius=3,
            progress_color=COLORS["accent"],
            fg_color=COLORS["surface_hi"],
        )
        self.progress.grid(row=0, column=4, sticky="e", padx=(12, 14))
        self.progress.set(0)
        self.progress.grid_remove()

    # ---- view switching --------------------------------------------------

    def show_view(self, key: str) -> None:
        """Swap the content area to ``key``."""
        if key not in dict(NAV_ITEMS):
            return
        if key not in self._views:
            self._views[key] = self._create_view(key)

        view = self._views[key]
        for other in self._views.values():
            other.grid_forget()
        view.grid(row=0, column=0, sticky="nsew")
        self._current_view = key

        # Let a view populate itself the first time it becomes visible.
        on_shown = getattr(view, "on_shown", None)
        if callable(on_shown):
            on_shown()

        for nav_key, button in self._nav_buttons.items():
            active = nav_key == key
            button.configure(
                fg_color=COLORS["accent_soft"] if active else "transparent",
                text_color=COLORS["accent"] if active else COLORS["text_muted"],
            )

    def _create_view(self, key: str) -> ctk.CTkFrame:
        if key == "available":
            return AvailableView(self.content, self)
        if key == "wrapped":
            return WrappedView(self.content, self)
        return SettingsView(self.content, self)

    def current_view(self) -> Optional[ctk.CTkFrame]:
        if self._current_view is None:
            return None
        return self._views.get(self._current_view)

    # ---- status / busy ---------------------------------------------------

    def set_status(self, text: str, tone: str = "neutral") -> None:
        self.status_pill.set_state(text, tone)

    def _on_busy_change(self, pending: int) -> None:
        if pending > 0:
            # Only show the bar while something is actually running.
            self.progress.grid()
            self.progress.start()
            self.set_status(f"Working… ({pending} task{'s' if pending > 1 else ''})", "accent")
        else:
            self.progress.stop()
            self.progress.set(0)
            self.progress.grid_remove()
            self.set_status("Ready.", "ok")

    def _refresh_cli_status(self) -> None:
        resolved = find_cli(self.app_config.cli_path)
        # The Settings override field calls this on every keystroke, so act (and
        # log) only when the outcome actually changes, not on each character.
        key = str(resolved) if resolved is not None else None
        if key == self._last_cli_resolution:
            return
        self._last_cli_resolution = key

        if resolved is None:
            self.cli_pill.set_state("Executable not found", "error")
            self.cli_path_label.configure(
                text="Place lmstudio-caplift.exe next to this UI, or set a path in Settings.",
                text_color=COLORS["error"],
            )
            self.log(
                "lmstudio-caplift.exe was not found next to this UI. "
                "Put both executables in the same folder, or set a path in Settings.",
                "warn",
            )
        else:
            self.cli_pill.set_state("Executable found", "ok")
            # Split the path so Tk wraps on a separator instead of mid-word.
            self.cli_path_label.configure(
                text=f"{resolved.parent}\\\n{resolved.name}",
                text_color=COLORS["text_dim"],
            )

    # ---- lifecycle -------------------------------------------------------

    def _startup_refresh(self) -> None:
        self.log(f"{APP_NAME} started.", "info")
        self.log(f"Config file: {config_path()}", "info")
        for warning in self._startup_warnings:
            self.log(warning, "warn")
        self._refresh_cli_status()

        # Build both data views first: show_view() is what creates them, so
        # reading self._views before this point yields nothing to refresh.
        self.show_view("wrapped")
        self.show_view("available")

        wrapped_view = self._views.get("wrapped")
        available_view = self._views.get("available")

        # The tracked list works without LM Studio, so load it immediately.
        if isinstance(wrapped_view, WrappedView):
            wrapped_view.refresh()

        # Installed models need LM Studio running; a failure explains itself.
        if isinstance(available_view, AvailableView):
            available_view.refresh()

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-r>", lambda _event: self._refresh_current())
        self.bind("<Control-R>", lambda _event: self._refresh_current())
        self.bind("<F5>", lambda _event: self._refresh_current())
        for index, (key, _label) in enumerate(NAV_ITEMS, start=1):
            self.bind(f"<Control-Key-{index}>", lambda _event, k=key: self.show_view(k))
        self.bind("<Control-q>", lambda _event: self.on_close())

    def _refresh_current(self) -> None:
        view = self.current_view()
        refresh = getattr(view, "refresh", None)
        if callable(refresh):
            refresh()

    def on_close(self) -> None:
        """Save window state and exit, waiting briefly for in-flight work."""
        self._capture_geometry()
        error = save_config(self.app_config)
        if error:
            self.log(error, "warn")
        self.destroy()

    def report_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:
        """Keep Tk callback failures visible instead of silent.

        In a windowed build there is no stdout, so an unhandled exception in a
        widget callback would otherwise vanish without a trace.
        """
        import traceback as _traceback

        self.log("Unexpected UI error:", "error")
        self.log(
            "".join(_traceback.format_exception(exc_type, exc_value, exc_traceback)).rstrip(),
            "stderr",
        )
        self.set_status(f"UI error: {exc_value}", "error")
