"""Wrapped-models view: what caplift has already registered."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Dict, Optional

import customtkinter as ctk

from ..cli_runner import CliRunner
from ..models import WrappedModel
from .dialogs import MessageDialog
from .theme import COLORS, FONTS
from .widgets import DataTable, SectionCard

COLUMNS = (
    ("wrapper", "Wrapper id", 280),
    ("model", "Wrapped model", 400),
    ("base", "Base template", 180),
    ("updated", "Updated", 130),
)

# Shown inside the detail box: a wrapping text widget handles long paths and
# narrow panels far better than a fixed-wraplength label does across DPI scales.
DETAIL_FOOTER = (
    "\n\nNote: lmstudio-caplift has no uninstall command. To remove a wrapper, delete its "
    "target folder and remove its entry from the registry — both are listed above."
)


class WrappedView(ctk.CTkFrame):
    """Everything tracked in ``.lmstudio-caplift.json``."""

    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app

        self._wrapped: Dict[str, WrappedModel] = {}
        self._selected: Optional[WrappedModel] = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_body()

    # ---- construction ---------------------------------------------------

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)

        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            titles,
            text="Wrapped models",
            font=FONTS.title,
            text_color=COLORS["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.subtitle = ctk.CTkLabel(
            titles,
            text="Tracked by the caplift registry. This list works without LM Studio running.",
            font=FONTS.small,
            text_color=COLORS["text_muted"],
            anchor="w",
        )
        self.subtitle.grid(row=1, column=0, sticky="w", pady=(2, 0))

        self.refresh_button = ctk.CTkButton(
            header,
            text="Refresh",
            width=110,
            height=32,
            font=FONTS.body,
            fg_color="transparent",
            hover_color=COLORS["surface_hi"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border_hi"],
            command=self.refresh,
        )
        self.refresh_button.grid(row=0, column=1, sticky="e")

    def _build_body(self) -> None:
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2, minsize=380)
        body.grid_rowconfigure(0, weight=1)

        table_card = SectionCard(body, padding=8)
        table_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        table_card.body.grid_rowconfigure(0, weight=1)
        self.table = DataTable(table_card.body, columns=COLUMNS, on_select=self._on_row_selected)
        self.table.grid(row=0, column=0, sticky="nsew")

        detail_card = SectionCard(body, title="Wrapper detail")
        detail_card.grid(row=0, column=1, sticky="nsew")
        panel = detail_card.body
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)

        self.detail_title = ctk.CTkLabel(
            panel,
            text="Select a wrapper to inspect it.",
            font=FONTS.small_bold,
            text_color=COLORS["text"],
            anchor="w",
            justify="left",
            wraplength=190,
        )
        self.detail_title.grid(row=0, column=0, sticky="ew")

        self.detail_box = ctk.CTkTextbox(
            panel,
            fg_color=COLORS["console_bg"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8,
            font=FONTS.mono_small,
            text_color=COLORS["text_muted"],
            wrap="word",
        )
        self.detail_box.grid(row=1, column=0, sticky="nsew", pady=(10, 10))
        self.detail_box.configure(state="disabled")
        self._show_detail_text("Reading the caplift registry…")

        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew")
        actions.grid_columnconfigure(0, weight=1)

        self.open_button = ctk.CTkButton(
            actions,
            text="Open target folder",
            height=34,
            font=FONTS.body,
            fg_color="transparent",
            hover_color=COLORS["surface_hi"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border_hi"],
            state="disabled",
            command=self._open_target_folder,
        )
        self.open_button.grid(row=0, column=0, sticky="ew")

    # ---- loading --------------------------------------------------------

    def refresh(self) -> None:
        """Reload the tracked list. Does not need LM Studio."""
        self.refresh_button.configure(state="disabled", text="Loading…")
        self.app.log("list --json", "command")

        def work():
            runner: CliRunner = self.app.build_runner()
            return runner.list_tracked()

        def done(registry):
            self.refresh_button.configure(state="normal", text="Refresh")
            self.set_wrapped(registry.wrapped)
            self.app.log(f"Loaded {len(registry.wrapped)} wrapper(s).", "ok")

        def failed(exc):
            self.refresh_button.configure(state="normal", text="Refresh")
            self.app.report_error("Could not read the caplift registry", exc)
            self.subtitle.configure(text="Could not read the registry. See Output below.", text_color=COLORS["warn"])

        self.app.run_task(work, on_success=done, on_error=failed, label="list tracked")

    def set_wrapped(self, wrapped) -> None:
        self._wrapped = {item.wrapper_model_id: item for item in wrapped}
        self._selected = None
        rows = []
        for item in self._wrapped.values():
            rows.append(
                (
                    item.wrapper_model_id,
                    (
                        item.wrapper_model_id,
                        item.model_key,
                        item.base_model_id or "—",
                        item.updated_display,
                    ),
                    "normal",
                )
            )
        self.table.set_rows(rows)

        if not rows:
            self.detail_title.configure(text="No wrappers tracked yet.", text_color=COLORS["text_muted"])
            self._show_detail_text(
                "Create one from the Available models tab. The registry is written next to the "
                "LM Studio hub models directory."
            )
            self.open_button.configure(state="disabled")
        else:
            self.subtitle.configure(
                text=f"{len(rows)} wrapper(s) tracked by the caplift registry.",
                text_color=COLORS["text_muted"],
            )
            self._show_empty_detail()

    def _show_empty_detail(self) -> None:
        """Placeholder so the detail pane is never a blank void."""
        self.detail_title.configure(text="No wrapper selected", text_color=COLORS["text_muted"])
        self._show_detail_text(
            "Select a wrapper on the left to see its wrapped model, base template, "
            "timestamps, and target folder."
        )
        self.open_button.configure(state="disabled")

    def _on_row_selected(self, row_id: Optional[str]) -> None:
        if not row_id or row_id not in self._wrapped:
            self._selected = None
            self._show_empty_detail()
            return
        item = self._wrapped[row_id]
        self._selected = item
        self.detail_title.configure(text=item.wrapper_model_id, text_color=COLORS["text"])

        lines = [
            f"wrapped model : {item.model_key}",
            f"base template : {item.base_model_id or '—'}",
            f"created       : {item.created_display}",
            f"updated       : {item.updated_display}",
            f"target dir    : {item.target_dir or '—'}",
        ]
        if item.raw:
            lines.append("")
            lines.append("registry entry:")
            lines.append(json.dumps(dict(item.raw), indent=2, sort_keys=True))
        self._show_detail_text("\n".join(lines))

        exists = bool(item.target_path and item.target_path.is_dir())
        self.open_button.configure(state="normal" if exists else "disabled")

    def _show_detail_text(self, text: str) -> None:
        self.detail_box.configure(state="normal")
        self.detail_box.delete("1.0", "end")
        self.detail_box.insert("1.0", text + DETAIL_FOOTER)
        self.detail_box.configure(state="disabled")

    # ---- actions --------------------------------------------------------

    def _open_target_folder(self) -> None:
        item = self._selected
        if item is None or item.target_path is None:
            return
        target = item.target_path
        if not target.is_dir():
            MessageDialog.show(
                self.app,
                "Folder not found",
                f"{target} does not exist. The registry entry may be stale.",
                tone="error",
            )
            return
        self._reveal(target)

    def _reveal(self, path: Path) -> None:
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif os.uname().sysname == "Darwin":  # pragma: no cover - platform specific
                subprocess.Popen(["open", str(path)])
            else:  # pragma: no cover - platform specific
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            MessageDialog.show(self.app, "Could not open folder", str(exc), tone="error")
