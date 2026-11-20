"""Modal dialogs: confirmation, preview, and messages."""
from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple

import customtkinter as ctk

from ..parser import DryRunPreview
from .theme import COLORS, FONTS
from .wolf import draw_wolf_head


def center_on_parent(window, parent, width: int, height: int) -> None:
    """Size and position ``window`` centred over ``parent``."""
    window.update_idletasks()
    try:
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
    except Exception:  # pragma: no cover - parent may be unmapped
        parent_x = parent_y = 0
        parent_w = parent_h = 0

    x = parent_x + max(0, (parent_w - width) // 2)
    y = parent_y + max(0, (parent_h - height) // 3)
    window.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")


class _BaseDialog(ctk.CTkToplevel):
    """Shared modal plumbing."""

    def __init__(self, parent, title: str, width: int, height: int, **kwargs) -> None:
        super().__init__(parent, fg_color=COLORS["bg"], **kwargs)
        self._parent = parent
        self.title(title)
        self.resizable(True, True)
        self.minsize(360, 200)
        center_on_parent(self, parent, width, height)
        self.grid_columnconfigure(0, weight=1)

        self.transient(parent)
        self.after(10, self._grab)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda _event: self._on_close())

    def _grab(self) -> None:
        try:
            self.grab_set()
            self.lift()
            self.focus_force()
        except Exception:  # pragma: no cover - grabbing is best-effort
            pass

    def _on_close(self) -> None:
        try:
            self.grab_release()
        except Exception:  # pragma: no cover
            pass
        self.destroy()


class ConfirmDialog(_BaseDialog):
    """Yes/no confirmation with an optional warning tone."""

    def __init__(
        self,
        parent,
        title: str,
        body: str,
        detail_lines: Sequence[str] = (),
        confirm_text: str = "Confirm",
        cancel_text: str = "Cancel",
        danger: bool = False,
    ) -> None:
        super().__init__(parent, title, width=520, height=300 if detail_lines else 240)
        self.result = False

        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 8))
        header.grid_columnconfigure(1, weight=1)

        mark_size = 34
        canvas = ctk.CTkCanvas(
            header,
            width=mark_size,
            height=mark_size,
            highlightthickness=0,
            bd=0,
            bg=COLORS["bg"],
        )
        draw_wolf_head(
            canvas,
            mark_size / 2,
            mark_size / 2,
            mark_size * 0.85,
            outline=COLORS["error"] if danger else COLORS["accent"],
        )
        canvas.grid(row=0, column=0, sticky="n", padx=(0, 12))

        ctk.CTkLabel(
            header,
            text=body,
            font=FONTS.body,
            text_color=COLORS["text"],
            anchor="w",
            justify="left",
            wraplength=420,
        ).grid(row=0, column=1, sticky="ew")

        if detail_lines:
            details = ctk.CTkTextbox(
                self,
                fg_color=COLORS["console_bg"],
                border_width=1,
                border_color=COLORS["border"],
                corner_radius=8,
                font=FONTS.mono_small,
                text_color=COLORS["text_muted"],
                wrap="word",
            )
            details.grid(row=1, column=0, sticky="nsew", padx=20, pady=(4, 8))
            details.insert("1.0", "\n".join(detail_lines))
            details.configure(state="disabled")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 18))
        buttons.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            buttons,
            text=cancel_text,
            width=110,
            height=34,
            font=FONTS.body,
            fg_color="transparent",
            hover_color=COLORS["surface_hi"],
            text_color=COLORS["text_muted"],
            border_width=1,
            border_color=COLORS["border"],
            command=self._cancel,
        ).grid(row=0, column=1, padx=(0, 8))

        ctk.CTkButton(
            buttons,
            text=confirm_text,
            width=140,
            height=34,
            font=FONTS.body_bold,
            fg_color=COLORS["error"] if danger else COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["accent_text"] if not danger else "#1b0d0d",
            command=self._confirm,
        ).grid(row=0, column=2)

        self.bind("<Return>", lambda _event: self._confirm())

    def _confirm(self) -> None:
        self.result = True
        self._on_close()

    def _cancel(self) -> None:
        self.result = False
        self._on_close()

    @classmethod
    def ask(cls, parent, title: str, body: str, **kwargs) -> bool:
        dialog = cls(parent, title=title, body=body, **kwargs)
        parent.wait_window(dialog)
        return dialog.result


class PreviewDialog(_BaseDialog):
    """Shows the files a wrap would generate, straight from ``--dry-run``."""

    def __init__(self, parent, preview: DryRunPreview, heading: str = "Dry run preview") -> None:
        files: Tuple[Tuple[str, str], ...] = preview.files
        super().__init__(parent, heading, width=880, height=640)

        self.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            self,
            text=heading,
            font=FONTS.heading,
            text_color=COLORS["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 6))

        facts = [
            ("Wrapper", preview.wrapper_model_id or "—"),
            ("Model key", preview.model_key or "—"),
            ("Base template", preview.base_model_id or "—"),
            ("Target directory", preview.target_dir or "—"),
        ]
        summary = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=8, border_width=1, border_color=COLORS["border"])
        summary.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))
        summary.grid_columnconfigure(1, weight=1)
        for index, (label, value) in enumerate(facts):
            ctk.CTkLabel(
                summary,
                text=label,
                font=FONTS.small_bold,
                text_color=COLORS["text_muted"],
                anchor="w",
            ).grid(row=index, column=0, sticky="w", padx=(12, 10), pady=(8 if index == 0 else 2, 8 if index == len(facts) - 1 else 2))
            ctk.CTkLabel(
                summary,
                text=value,
                font=FONTS.mono_small,
                text_color=COLORS["text"],
                anchor="w",
                justify="left",
                wraplength=620,
            ).grid(row=index, column=1, sticky="ew", padx=(0, 12), pady=(8 if index == 0 else 2, 8 if index == len(facts) - 1 else 2))

        if files:
            tabs = ctk.CTkTabview(
                self,
                fg_color=COLORS["surface"],
                segmented_button_fg_color=COLORS["surface_alt"],
                segmented_button_selected_color=COLORS["accent"],
                segmented_button_selected_hover_color=COLORS["accent_hover"],
                segmented_button_unselected_color=COLORS["surface_alt"],
                segmented_button_unselected_hover_color=COLORS["surface_hi"],
                text_color=COLORS["text"],
                border_width=1,
                border_color=COLORS["border"],
                corner_radius=8,
            )
            tabs.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))

            for path, content in files:
                name = path.replace("\\", "/").rsplit("/", 1)[-1]
                tab = tabs.add(name)
                tab.grid_columnconfigure(0, weight=1)
                tab.grid_rowconfigure(1, weight=1)

                ctk.CTkLabel(
                    tab,
                    text=path,
                    font=FONTS.mono_small,
                    text_color=COLORS["text_dim"],
                    anchor="w",
                ).grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))

                box = ctk.CTkTextbox(
                    tab,
                    fg_color=COLORS["console_bg"],
                    border_width=0,
                    corner_radius=6,
                    font=FONTS.mono,
                    text_color=COLORS["text"],
                    wrap="none",
                )
                box.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
                box.insert("1.0", content)
                box.configure(state="disabled")

                ctk.CTkButton(
                    tab,
                    text="Copy",
                    width=70,
                    height=26,
                    font=FONTS.small,
                    fg_color="transparent",
                    hover_color=COLORS["surface_hi"],
                    text_color=COLORS["text_muted"],
                    border_width=1,
                    border_color=COLORS["border"],
                    command=lambda text=content: self._copy(text),
                ).grid(row=0, column=1, sticky="e", padx=(6, 6), pady=(6, 4))
        else:
            fallback = ctk.CTkTextbox(
                self,
                fg_color=COLORS["console_bg"],
                border_width=1,
                border_color=COLORS["border"],
                corner_radius=8,
                font=FONTS.mono,
                text_color=COLORS["text_muted"],
                wrap="word",
            )
            fallback.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))
            fallback.insert("1.0", preview.raw_text or "The CLI produced no output.")
            fallback.configure(state="disabled")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 18))
        footer.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            footer,
            text="Nothing has been written yet — this is a dry run.",
            font=FONTS.small,
            text_color=COLORS["text_dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            footer,
            text="Close",
            width=110,
            height=34,
            font=FONTS.body,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["accent_text"],
            command=self._on_close,
        ).grid(row=0, column=1, sticky="e")

    def _copy(self, text: str) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:  # pragma: no cover - clipboard is best-effort
            pass

    @classmethod
    def show(cls, parent, preview: DryRunPreview, heading: str = "Dry run preview") -> None:
        dialog = cls(parent, preview=preview, heading=heading)
        parent.wait_window(dialog)


class MessageDialog(_BaseDialog):
    """Informational dialog with a single dismiss button."""

    def __init__(self, parent, title: str, body: str, detail_lines: Iterable[str] = (), tone: str = "accent") -> None:
        super().__init__(parent, title, width=560, height=280)
        details = list(detail_lines)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 8))
        header.grid_columnconfigure(1, weight=1)

        mark_size = 34
        canvas = ctk.CTkCanvas(
            header,
            width=mark_size,
            height=mark_size,
            highlightthickness=0,
            bd=0,
            bg=COLORS["bg"],
        )
        draw_wolf_head(
            canvas,
            mark_size / 2,
            mark_size / 2,
            mark_size * 0.85,
            outline=COLORS.get(tone, COLORS["accent"]),
        )
        canvas.grid(row=0, column=0, sticky="n", padx=(0, 12))

        ctk.CTkLabel(
            header,
            text=body,
            font=FONTS.body,
            text_color=COLORS["text"],
            anchor="w",
            justify="left",
            wraplength=460,
        ).grid(row=0, column=1, sticky="ew")

        if details:
            box = ctk.CTkTextbox(
                self,
                fg_color=COLORS["console_bg"],
                border_width=1,
                border_color=COLORS["border"],
                corner_radius=8,
                font=FONTS.mono_small,
                text_color=COLORS["text_muted"],
                wrap="word",
            )
            box.grid(row=1, column=0, sticky="nsew", padx=20, pady=(4, 8))
            box.insert("1.0", "\n".join(details))
            box.configure(state="disabled")

        ctk.CTkButton(
            self,
            text="Close",
            width=110,
            height=34,
            font=FONTS.body,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["accent_text"],
            command=self._on_close,
        ).grid(row=2, column=0, sticky="e", padx=20, pady=(8, 18))

    @classmethod
    def show(cls, parent, title: str, body: str, **kwargs) -> None:
        dialog = cls(parent, title=title, body=body, **kwargs)
        parent.wait_window(dialog)
