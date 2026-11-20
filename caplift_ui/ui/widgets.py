"""Reusable widgets shared by the views."""
from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import customtkinter as ctk

from .theme import COLORS, FONTS, TREEVIEW_STYLE, ui_family

# Upper bound for auto-fitted column widths, so one very long model key cannot
# squeeze every other column off screen.
MAX_COLUMN_WIDTH = 560


class SectionCard(ctk.CTkFrame):
    """A titled surface panel.

    Views build their layout out of these so spacing and borders stay uniform.
    """

    def __init__(
        self,
        master,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        padding: int = 14,
        subtitle_wraplength: int = 520,
        **kwargs,
    ) -> None:
        kwargs.setdefault("fg_color", COLORS["surface"])
        kwargs.setdefault("corner_radius", 10)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", COLORS["border"])
        super().__init__(master, **kwargs)

        self.padding = padding
        self.grid_columnconfigure(0, weight=1)

        self.header = None
        row = 0
        if title is not None:
            self.header = ctk.CTkFrame(self, fg_color="transparent")
            self.header.grid(row=row, column=0, sticky="ew", padx=padding, pady=(padding, 0))
            self.header.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                self.header,
                text=title,
                font=FONTS.heading,
                text_color=COLORS["text"],
                anchor="w",
            ).grid(row=0, column=0, sticky="w")

            if subtitle:
                ctk.CTkLabel(
                    self.header,
                    text=subtitle,
                    font=FONTS.small,
                    text_color=COLORS["text_muted"],
                    anchor="w",
                    justify="left",
                    wraplength=subtitle_wraplength,
                ).grid(row=1, column=0, sticky="w", pady=(2, 0))
            row += 1

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=row, column=0, sticky="nsew", padx=padding, pady=(10 if title else padding, padding))
        self.body.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(row, weight=1)


class StatusPill(ctk.CTkLabel):
    """A small rounded badge whose colour encodes a state."""

    TONES: Dict[str, Tuple[str, str]] = {
        "neutral": (COLORS["surface_hi"], COLORS["text_muted"]),
        "ok": (COLORS["ok_soft"], COLORS["ok"]),
        "warn": (COLORS["warn_soft"], COLORS["warn"]),
        "error": (COLORS["error_soft"], COLORS["error"]),
        "accent": (COLORS["accent_soft"], COLORS["accent"]),
    }

    def __init__(self, master, text: str = "", tone: str = "neutral", **kwargs) -> None:
        fg, text_color = self.TONES.get(tone, self.TONES["neutral"])
        kwargs.setdefault("corner_radius", 6)
        kwargs.setdefault("font", FONTS.small_bold)
        super().__init__(master, text=text, fg_color=fg, text_color=text_color, **kwargs)
        self._tone = tone

    def set_state(self, text: str, tone: str = "neutral") -> None:
        fg, text_color = self.TONES.get(tone, self.TONES["neutral"])
        self._tone = tone
        self.configure(text=text, fg_color=fg, text_color=text_color)


class LabeledEntry(ctk.CTkFrame):
    """A label above a text entry, with an optional hint line underneath."""

    def __init__(
        self,
        master,
        label: str,
        hint: str = "",
        placeholder: str = "",
        width: int = 0,
        hint_wraplength: int = 520,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text=label,
            font=FONTS.small_bold,
            text_color=COLORS["text_muted"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self.entry = ctk.CTkEntry(
            self,
            placeholder_text=placeholder,
            font=FONTS.mono,
            fg_color=COLORS["surface_alt"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            height=32,
            **(dict(width=width) if width else {}),
        )
        self.entry.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        self.hint = ctk.CTkLabel(
            self,
            text=hint,
            font=FONTS.small,
            text_color=COLORS["text_dim"],
            anchor="w",
            justify="left",
            wraplength=hint_wraplength,
        )
        self.hint.grid(row=2, column=0, sticky="w", pady=(3, 0))
        if not hint:
            self.hint.grid_remove()

    # ---- passthroughs --------------------------------------------------

    def get(self) -> str:
        return self.entry.get().strip()

    def set(self, value: str) -> None:
        """Replace the entry contents.

        A disabled Tk entry ignores ``insert``/``delete``, so the state is
        temporarily opened and restored — otherwise values silently vanish when
        a form is populated while still disabled.
        """
        current = self.entry.get()
        if current == value:
            return
        previous_state = self.entry.cget("state")
        if previous_state == "disabled":
            self.entry.configure(state="normal")
        try:
            self.entry.delete(0, "end")
            if value:
                self.entry.insert(0, value)
        finally:
            if previous_state == "disabled":
                self.entry.configure(state=previous_state)

    def set_hint(self, text: str, tone: str = "muted") -> None:
        color = {
            "muted": COLORS["text_dim"],
            "ok": COLORS["ok"],
            "warn": COLORS["warn"],
            "error": COLORS["error"],
        }.get(tone, COLORS["text_dim"])
        self.hint.configure(text=text, text_color=color)
        if text:
            self.hint.grid()
        else:
            self.hint.grid_remove()

    def bind_change(self, callback: Callable[[], None]) -> None:
        self.entry.bind("<KeyRelease>", lambda _event: callback())

    def set_enabled(self, enabled: bool) -> None:
        self.entry.configure(state="normal" if enabled else "disabled")


class DataTable(ctk.CTkFrame):
    """A ttk.Treeview styled to match the dark theme.

    Rows are keyed by an opaque id so callers can map a selection back to a model
    without parsing display text.
    """

    def __init__(
        self,
        master,
        columns: Sequence[Tuple[str, str, int]],
        on_select: Optional[Callable[[Optional[str]], None]] = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("fg_color", COLORS["surface"])
        kwargs.setdefault("corner_radius", 10)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", COLORS["border"])
        super().__init__(master, **kwargs)

        from tkinter import ttk

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._columns = list(columns)
        self._headings = {name: heading for name, heading, _width in self._columns}
        self._on_select = on_select
        self._last_rows: List[Tuple[str, Sequence[str], str]] = []
        self._applied: Dict[str, int] = {}
        self._refit_job = None

        column_ids = [name for name, _heading, _width in self._columns]
        self.tree = ttk.Treeview(
            self,
            columns=column_ids,
            show="headings",
            selectmode="browse",
            style=TREEVIEW_STYLE,
        )
        for name, heading, width in self._columns:
            self.tree.heading(name, text=heading, anchor="w")
            self.tree.column(name, width=width, minwidth=80, anchor="w", stretch=(name == column_ids[0]))

        self.tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)

        self.scrollbar = ctk.CTkScrollbar(self, command=self.tree.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=6)
        self.tree.configure(yscrollcommand=self.scrollbar.set)

        self.tree.bind("<<TreeviewSelect>>", self._handle_select)
        self.bind("<Configure>", self._on_configure)
        self.tree.tag_configure("missing_template", foreground=COLORS["warn"])
        self.tree.tag_configure("wrapped", foreground=COLORS["text_dim"])
        self.tree.tag_configure("normal", foreground=COLORS["text"])

    # ---- content -------------------------------------------------------

    def set_rows(self, rows: Iterable[Tuple[str, Sequence[str], str]]) -> None:
        """Replace all rows.

        Each row is ``(row_id, cell_values, tag)``.
        """
        selected = self.selected_id()
        self.tree.delete(*self.tree.get_children())
        collected = list(rows)
        for row_id, values, tag in collected:
            self.tree.insert("", "end", iid=row_id, values=tuple(values), tags=(tag,))
        self._last_rows = collected
        self._autofit_columns(collected)
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
            self.tree.see(selected)

    def _autofit_columns(self, rows: Sequence[Tuple[str, Sequence[str], str]]) -> None:
        """Size columns to their content, then shrink to fit the visible width.

        Model keys and wrapper ids vary a lot in length, so fixed widths either
        truncate them or waste space. Without the shrink-to-fit step the widest
        columns push the last one off the right edge, where there is no
        horizontal scrollbar to reach it.
        """
        try:
            from tkinter import font as tkfont

            measure = tkfont.Font(family=ui_family(), size=11).measure
        except Exception:  # pragma: no cover - fall back to the declared widths
            return

        padding = 28
        widths: List[int] = []
        minimums: List[int] = []
        for index, (name, _heading, declared) in enumerate(self._columns):
            widest = measure(self._headings[name])
            for _row_id, values, _tag in rows:
                if index < len(values):
                    widest = max(widest, measure(str(values[index])))
            # Minimum keeps the heading readable, so columns are never so narrow
            # that their own header is cut off.
            minimums.append(max(80, measure(self._headings[name]) + 22, declared // 3))
            widths.append(max(minimums[-1], min(widest + padding, MAX_COLUMN_WIDTH)))

        available = self.winfo_width() - 30  # scrollbar plus padding
        total = sum(widths)
        if available > 140 and total > available:
            # Take space from whichever column has the most slack, so a very long
            # model key gives way before a short timestamp column does.
            overflow = total - available
            for index in sorted(range(len(widths)), key=lambda i: widths[i] - minimums[i], reverse=True):
                if overflow <= 0:
                    break
                take = min(widths[index] - minimums[index], overflow)
                widths[index] -= take
                overflow -= take

        # Re-applying identical widths would re-trigger <Configure> forever.
        if all(abs(widths[i] - self._applied.get(name, -1)) <= 2 for i, (name, _h, _w) in enumerate(self._columns)):
            return

        for index, (name, _heading, _declared) in enumerate(self._columns):
            self.tree.column(name, width=widths[index], minwidth=widths[index])
            self._applied[name] = widths[index]

    def _on_configure(self, _event=None) -> None:
        """Re-fit after a resize, debounced so dragging stays smooth."""
        if self._refit_job is not None:
            try:
                self.after_cancel(self._refit_job)
            except Exception:  # pragma: no cover - job may already have run
                pass
        self._refit_job = self.after(90, self._refit)

    def _refit(self) -> None:
        self._refit_job = None
        if self._last_rows:
            self._autofit_columns(self._last_rows)

    def clear(self) -> None:
        self.tree.delete(*self.tree.get_children())

    def row_count(self) -> int:
        return len(self.tree.get_children())

    # ---- selection -----------------------------------------------------

    def selected_id(self) -> Optional[str]:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def select_first(self) -> None:
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])

    def _handle_select(self, _event=None) -> None:
        if self._on_select is not None:
            self._on_select(self.selected_id())


class Console(ctk.CTkFrame):
    """Read-only output pane that shows commands and their results."""

    LEVEL_COLORS = {
        "command": COLORS["accent"],
        "info": COLORS["text_muted"],
        "stdout": COLORS["text"],
        "stderr": COLORS["error"],
        "ok": COLORS["ok"],
        "warn": COLORS["warn"],
        "error": COLORS["error"],
    }

    def __init__(self, master, height: int = 150, **kwargs) -> None:
        kwargs.setdefault("fg_color", COLORS["surface"])
        kwargs.setdefault("corner_radius", 10)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", COLORS["border"])
        super().__init__(master, **kwargs)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Output",
            font=FONTS.small_bold,
            text_color=COLORS["text_muted"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            header,
            text="Clear",
            width=64,
            height=24,
            font=FONTS.small,
            fg_color="transparent",
            hover_color=COLORS["surface_hi"],
            text_color=COLORS["text_muted"],
            border_width=1,
            border_color=COLORS["border"],
            command=self.clear,
        ).grid(row=0, column=1, sticky="e")

        self.text = ctk.CTkTextbox(
            self,
            height=height,
            fg_color=COLORS["console_bg"],
            border_width=0,
            corner_radius=8,
            font=FONTS.mono,
            text_color=COLORS["text_muted"],
            wrap="word",
        )
        self.text.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 12))
        self.text.configure(state="disabled")

        self._configure_tags()

    # ---- tag plumbing --------------------------------------------------

    def _text_widget(self):
        """The underlying tkinter.Text, which owns tag configuration."""
        return getattr(self.text, "_textbox", None) or self.text

    def _configure_tags(self) -> None:
        target = self._text_widget()
        configure = getattr(target, "tag_config", None)
        if configure is None:
            return
        for level, color in self.LEVEL_COLORS.items():
            try:
                configure(level, foreground=color)
            except Exception:  # pragma: no cover - cosmetic only
                pass

    # ---- writing -------------------------------------------------------

    def append(self, message: str, level: str = "info") -> None:
        if message is None:
            return
        level = level if level in self.LEVEL_COLORS else "info"
        self.text.configure(state="normal")
        try:
            self.text.insert("end", message.rstrip("\n") + "\n", level)
            self.text.see("end")
        finally:
            self.text.configure(state="disabled")

    def append_lines(self, lines: Iterable[str], level: str = "info") -> None:
        for line in lines:
            self.append(line, level)

    def rule(self, label: str = "") -> None:
        line = f"──── {label} " if label else "────"
        self.append(line.ljust(72, "─"), "info")

    def clear(self) -> None:
        self.text.configure(state="normal")
        try:
            self.text.delete("1.0", "end")
        finally:
            self.text.configure(state="disabled")
