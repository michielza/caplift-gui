"""Dark theme tokens for Caplift UI.

Colours and fonts live here so views never hardcode a hex value. The accent is a
wolf-amber that matches the sketch of the mascot; silver is the secondary.
"""
from __future__ import annotations

import sys
from typing import Dict

import customtkinter as ctk

# ---- palette ---------------------------------------------------------------

COLORS: Dict[str, str] = {
    "bg": "#0f1116",
    "surface": "#161a22",
    "surface_alt": "#1c212b",
    "surface_hi": "#242a36",
    "border": "#2b3140",
    "border_hi": "#3a4356",
    "text": "#e7e9ee",
    "text_muted": "#99a1b4",
    "text_dim": "#6d7588",
    "accent": "#e0a63c",
    "accent_hover": "#f2b954",
    "accent_press": "#c08e2f",
    "accent_soft": "#3a2f1a",
    "accent_text": "#1a1408",
    "silver": "#9fb3cc",
    "silver_soft": "#26303d",
    "ok": "#57b98a",
    "ok_soft": "#1e2f27",
    "warn": "#e0a63c",
    "warn_soft": "#33291a",
    "error": "#e0655f",
    "error_soft": "#341f1f",
    "console_bg": "#0c0e13",
}

# ---- font families ---------------------------------------------------------


def ui_family() -> str:
    """Preferred UI font family for the current platform."""
    if sys.platform.startswith("win"):
        return "Segoe UI"
    if sys.platform == "darwin":
        return "SF Pro Text"
    return "DejaVu Sans"


def mono_family() -> str:
    """Preferred monospace family for paths and generated files."""
    if sys.platform.startswith("win"):
        return "Consolas"
    if sys.platform == "darwin":
        return "Menlo"
    return "DejaVu Sans Mono"


class Fonts:
    """Lazily created CTkFont objects.

    CTkFont needs a live Tk root, so these are built on first access rather than
    at import time.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, ctk.CTkFont] = {}

    def _make(self, key: str, family: str, size: int, weight: str = "normal") -> ctk.CTkFont:
        if key not in self._cache:
            self._cache[key] = ctk.CTkFont(family=family, size=size, weight=weight)
        return self._cache[key]

    @property
    def title(self) -> ctk.CTkFont:
        return self._make("title", ui_family(), 22, "bold")

    @property
    def heading(self) -> ctk.CTkFont:
        return self._make("heading", ui_family(), 15, "bold")

    @property
    def body(self) -> ctk.CTkFont:
        return self._make("body", ui_family(), 13)

    @property
    def body_bold(self) -> ctk.CTkFont:
        return self._make("body_bold", ui_family(), 13, "bold")

    @property
    def small(self) -> ctk.CTkFont:
        return self._make("small", ui_family(), 12)

    @property
    def small_bold(self) -> ctk.CTkFont:
        return self._make("small_bold", ui_family(), 12, "bold")

    @property
    def nav(self) -> ctk.CTkFont:
        return self._make("nav", ui_family(), 14)

    @property
    def mono(self) -> ctk.CTkFont:
        return self._make("mono", mono_family(), 12)

    @property
    def mono_small(self) -> ctk.CTkFont:
        return self._make("mono_small", mono_family(), 11)


FONTS = Fonts()

# ---- tk/ttk styling --------------------------------------------------------

TREEVIEW_STYLE = "Caplift.Treeview"
TREEVIEW_HEADING_STYLE = "Caplift.Treeview.Heading"


def apply_base_theme() -> None:
    """Configure CustomTkinter's appearance mode."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    ctk.set_widget_scaling(1.0)
    ctk.set_window_scaling(1.0)


def apply_ttk_theme(widget) -> None:
    """Style the classic ttk widgets (Treeview, scrollbars) to match the dark UI.

    CustomTkinter has no table widget, so the model lists use ttk.Treeview and
    need ``clam`` as the base theme for full colour control on Windows.
    """
    from tkinter import ttk

    style = ttk.Style(widget)
    try:
        style.theme_use("clam")
    except Exception:  # pragma: no cover - theme name always exists on Windows
        pass

    style.configure(
        TREEVIEW_STYLE,
        background=COLORS["surface"],
        fieldbackground=COLORS["surface"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        borderwidth=0,
        relief="flat",
        rowheight=26,
        font=(ui_family(), 11),
    )
    style.configure(
        TREEVIEW_HEADING_STYLE,
        background=COLORS["surface_alt"],
        foreground=COLORS["text_muted"],
        bordercolor=COLORS["border"],
        borderwidth=0,
        relief="flat",
        padding=(8, 6),
        font=(ui_family(), 11, "bold"),
    )
    style.map(
        TREEVIEW_STYLE,
        background=[("selected", COLORS["accent_soft"])],
        foreground=[("selected", COLORS["accent"])],
    )
    style.map(
        TREEVIEW_HEADING_STYLE,
        background=[("active", COLORS["surface_hi"])],
        foreground=[("active", COLORS["text"])],
    )

    # Mark: ttk draws focus rings we do not want.
    style.layout(
        TREEVIEW_STYLE,
        [("Treeview.treearea", {"sticky": "nswe"})],
    )

    for orientation, element in (("Vertical", "Vertical.TScrollbar"), ("Horizontal", "Horizontal.TScrollbar")):
        style.configure(
            element,
            background=COLORS["surface_hi"],
            troughcolor=COLORS["bg"],
            bordercolor=COLORS["bg"],
            arrowcolor=COLORS["text_muted"],
            borderwidth=0,
            relief="flat",
        )
        style.map(
            element,
            background=[("active", COLORS["border_hi"])],
        )
