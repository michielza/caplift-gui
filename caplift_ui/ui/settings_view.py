"""Settings view: where the CLI lives and how commands are run."""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ..config import config_path, find_cli
from ..cli_runner import CliRunner
from ..tasks import describe_exception
from .dialogs import ConfirmDialog, MessageDialog
from .theme import COLORS, FONTS
from .widgets import LabeledEntry, SectionCard, StatusPill


class SettingsView(ctk.CTkFrame):
    """Paths, timeout, and defaults."""

    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._loaded = False

        self.grid_columnconfigure(0, weight=1)

        wrapper = ctk.CTkScrollableFrame(self, fg_color="transparent")
        wrapper.grid(row=0, column=0, sticky="nsew")
        wrapper.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_cli_card(wrapper)
        self._build_paths_card(wrapper)
        self._build_behaviour_card(wrapper)

    def on_shown(self) -> None:
        """Populate on first display; later visits only re-check discovery.

        Reloading the whole form every time would discard unsaved edits.
        """
        if not self._loaded:
            self.reload()
        else:
            self._refresh_detected()

    # ---- cards ----------------------------------------------------------

    def _build_cli_card(self, master) -> None:
        card = SectionCard(
            master,
            title="caplift executable",
            subtitle="The UI looks for lmstudio-caplift.exe in its own folder first.",
        )
        card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        body = card.body

        self.detected_pill = StatusPill(body, text="Checking…", tone="neutral")
        self.detected_pill.grid(row=0, column=0, sticky="w")

        self.cli_field = LabeledEntry(
            body,
            label="Override path (optional)",
            hint="Leave blank to use the executable found next to this UI.",
            placeholder=r"C:\path\to\lmstudio-caplift.exe",
        )
        self.cli_field.grid(row=1, column=0, sticky="ew", pady=(12, 0))

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        ctk.CTkButton(
            buttons,
            text="Browse…",
            width=100,
            height=30,
            font=FONTS.small,
            fg_color="transparent",
            hover_color=COLORS["surface_hi"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border"],
            command=self._browse_cli,
        ).grid(row=0, column=0, padx=(0, 8))

        ctk.CTkButton(
            buttons,
            text="Auto-detect",
            width=120,
            height=30,
            font=FONTS.small,
            fg_color="transparent",
            hover_color=COLORS["surface_hi"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border"],
            command=self._auto_detect,
        ).grid(row=0, column=1, padx=(0, 8))

        ctk.CTkButton(
            buttons,
            text="Check version",
            width=130,
            height=30,
            font=FONTS.small,
            fg_color="transparent",
            hover_color=COLORS["surface_hi"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border"],
            command=self._check_version,
        ).grid(row=0, column=2)

    def _build_paths_card(self, master) -> None:
        card = SectionCard(
            master,
            title="LM Studio paths",
            subtitle="Only needed when auto-discovery picks the wrong location.",
        )
        card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        body = card.body

        self.hub_field = LabeledEntry(
            body,
            label="Hub models directory (--hub-models-dir)",
            hint=r"Blank uses %USERPROFILE%\.lmstudio\hub\models.",
            placeholder=r"C:\Users\you\.lmstudio\hub\models",
        )
        self.hub_field.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            body,
            text="Browse…",
            width=100,
            height=30,
            font=FONTS.small,
            fg_color="transparent",
            hover_color=COLORS["surface_hi"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border"],
            command=lambda: self._browse_into(self.hub_field, directory=True),
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))

        self.lms_field = LabeledEntry(
            body,
            label="lms executable (--lms, optional)",
            hint=r"Blank uses %USERPROFILE%\.lmstudio\bin\lms.exe, then PATH.",
            placeholder=r"C:\Users\you\.lmstudio\bin\lms.exe",
        )
        self.lms_field.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        ctk.CTkButton(
            body,
            text="Browse…",
            width=100,
            height=30,
            font=FONTS.small,
            fg_color="transparent",
            hover_color=COLORS["surface_hi"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border"],
            command=lambda: self._browse_into(self.lms_field, directory=False),
        ).grid(row=3, column=0, sticky="w", pady=(8, 0))

    def _build_behaviour_card(self, master) -> None:
        card = SectionCard(master, title="Behaviour")
        card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        body = card.body

        self.timeout_field = LabeledEntry(
            body,
            label="Command timeout (seconds)",
            hint="How long to wait for lmstudio-caplift before giving up.",
        )
        self.timeout_field.grid(row=0, column=0, sticky="ew")

        self.force_switch = ctk.CTkSwitch(
            body,
            text="Tick “allow overwriting” by default on the wrap form",
            font=FONTS.small,
            text_color=COLORS["text_muted"],
            progress_color=COLORS["warn"],
            button_color=COLORS["text"],
            button_hover_color=COLORS["accent_hover"],
        )
        self.force_switch.grid(row=1, column=0, sticky="w", pady=(16, 0))

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        actions.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            actions,
            text="Reload from disk",
            width=150,
            height=34,
            font=FONTS.body,
            fg_color="transparent",
            hover_color=COLORS["surface_hi"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border"],
            command=self.reload,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            actions,
            text="Save settings",
            width=150,
            height=34,
            font=FONTS.body_bold,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["accent_text"],
            command=self.save,
        ).grid(row=0, column=1, sticky="e")

        self.config_label = ctk.CTkLabel(
            body,
            text=f"Config file: {config_path()}",
            font=FONTS.small,
            text_color=COLORS["text_dim"],
            anchor="w",
            justify="left",
            wraplength=640,
        )
        self.config_label.grid(row=3, column=0, sticky="ew", pady=(12, 0))

    # ---- population -----------------------------------------------------

    def reload(self) -> None:
        """Fill the form from the in-memory config."""
        config = self.app.app_config
        self._loaded = True
        self.cli_field.set(config.cli_path or "")
        self.hub_field.set(config.hub_models_dir or "")
        self.lms_field.set(config.lms_path or "")
        self.timeout_field.set(str(config.timeout_seconds))
        if config.force_overwrite_by_default:
            self.force_switch.select()
        else:
            self.force_switch.deselect()
        self._refresh_detected()
        self.config_label.configure(text=f"Config file: {config_path()}")

    def _refresh_detected(self) -> None:
        resolved = find_cli(self.cli_field.get() or None)
        if resolved is None:
            self.detected_pill.set_state("lmstudio-caplift.exe not found", "error")
        else:
            self.detected_pill.set_state(f"Found: {resolved}", "ok")

    def save(self) -> None:
        """Validate and persist the form."""
        timeout_text = self.timeout_field.get()
        try:
            timeout = int(timeout_text) if timeout_text else 300
        except ValueError:
            MessageDialog.show(
                self.app,
                "Invalid timeout",
                "The timeout must be a whole number of seconds.",
                tone="error",
            )
            return
        if timeout < 5 or timeout > 3600:
            MessageDialog.show(
                self.app,
                "Invalid timeout",
                "Use a timeout between 5 and 3600 seconds.",
                tone="error",
            )
            return

        config = self.app.app_config
        cli_override = self.cli_field.get() or None
        if cli_override and not Path(cli_override).is_file():
            MessageDialog.show(
                self.app,
                "Executable not found",
                f"{cli_override} does not exist. Clear the override to use auto-detection.",
                tone="error",
            )
            return
        hub = self.hub_field.get() or None
        if hub and not Path(hub).is_dir():
            if not ConfirmDialog.ask(
                self.app,
                "Directory does not exist",
                f"{hub} does not exist yet. Save it anyway?",
                confirm_text="Save anyway",
            ):
                return
        lms = self.lms_field.get() or None
        if lms and not Path(lms).is_file():
            if not ConfirmDialog.ask(
                self.app,
                "lms executable not found",
                f"{lms} does not exist. Save it anyway?",
                confirm_text="Save anyway",
            ):
                return

        config.cli_path = cli_override
        config.hub_models_dir = hub
        config.lms_path = lms
        config.timeout_seconds = timeout
        config.force_overwrite_by_default = bool(self.force_switch.get())

        error = self.app.save_config()
        if error:
            MessageDialog.show(self.app, "Could not save", error, tone="error")
            return

        self._refresh_detected()
        self.app.on_config_changed()
        self.app.log(f"Settings saved to {config_path()}", "ok")

    # ---- helpers --------------------------------------------------------

    def _browse_cli(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.app,
            title="Select lmstudio-caplift executable",
            filetypes=[("lmstudio-caplift", "lmstudio-caplift*"), ("Executables", "*.exe"), ("All files", "*.*")],
        )
        if selected:
            self.cli_field.set(selected)
            self._refresh_detected()

    def _browse_into(self, field: LabeledEntry, directory: bool) -> None:
        if directory:
            selected = filedialog.askdirectory(parent=self.app, title="Select directory")
        else:
            selected = filedialog.askopenfilename(
                parent=self.app,
                title="Select executable",
                filetypes=[("Executables", "*.exe"), ("All files", "*.*")],
            )
        if selected:
            field.set(selected)

    def _auto_detect(self) -> None:
        self.cli_field.set("")
        self._refresh_detected()
        resolved = find_cli(None)
        if resolved is None:
            MessageDialog.show(
                self.app,
                "Not found",
                "lmstudio-caplift.exe was not found next to this UI. Place the two executables "
                "in the same folder, or set an explicit path.",
                tone="error",
            )
        else:
            self.app.log(f"Auto-detected executable: {resolved}", "ok")

    def _check_version(self) -> None:
        try:
            runner = self.app.build_runner()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            MessageDialog.show(self.app, "CLI not available", describe_exception(exc), tone="error")
            return

        def work():
            return runner.version()

        def done(version: str):
            self.app.log(f"lmstudio-caplift version: {version}", "ok")
            MessageDialog.show(self.app, "Version", f"lmstudio-caplift reports:\n\n{version}")

        def failed(exc):
            self.app.report_error("Could not read the CLI version", exc)

        self.app.run_task(work, on_success=done, on_error=failed, label="version")
