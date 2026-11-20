"""The wolf accent: a small vector mascot drawn straight onto a Tk canvas.

Drawn with polygons rather than an emoji glyph, because emoji rendering on Tk is
inconsistent across Windows font stacks and a blank box in the header would look
like a bug.
"""
from __future__ import annotations

from typing import Sequence, Tuple

from .theme import COLORS

# Normalised outline of a stylised wolf head, y growing downward.
# Two upright ears, angular cheeks, tapering muzzle.
_HEAD_OUTLINE: Sequence[Tuple[float, float]] = (
    (0.30, 0.20),  # left ear base, outer
    (0.235, 0.03),  # left ear tip
    (0.42, 0.185),  # left ear base, inner
    (0.50, 0.155),  # brow dip
    (0.58, 0.185),  # right ear base, inner
    (0.765, 0.03),  # right ear tip
    (0.70, 0.20),  # right ear base, outer
    (0.865, 0.36),  # right cheek
    (0.735, 0.535),  # right jaw
    (0.575, 0.625),  # right muzzle
    (0.50, 0.90),  # chin
    (0.425, 0.625),  # left muzzle
    (0.265, 0.535),  # left jaw
    (0.135, 0.36),  # left cheek
)

_LEFT_EYE: Sequence[Tuple[float, float]] = (
    (0.315, 0.375),
    (0.425, 0.325),
    (0.445, 0.390),
    (0.335, 0.415),
)

_RIGHT_EYE: Sequence[Tuple[float, float]] = (
    (0.685, 0.375),
    (0.575, 0.325),
    (0.555, 0.390),
    (0.665, 0.415),
)

_NOSE: Sequence[Tuple[float, float]] = (
    (0.452, 0.665),
    (0.548, 0.665),
    (0.50, 0.745),
)


def _scale(points: Sequence[Tuple[float, float]], x: float, y: float, size: float):
    flat = []
    for nx, ny in points:
        flat.append(x + (nx - 0.5) * size)
        flat.append(y + (ny - 0.5) * size)
    return flat


def draw_wolf_head(
    canvas,
    x: float,
    y: float,
    size: float,
    outline: str = None,
    eye: str = None,
    nose: str = None,
) -> None:
    """Draw a wolf head centred on ``(x, y)``.

    Args:
        canvas: any ``tkinter.Canvas``.
        x, y: centre point in canvas coordinates.
        size: bounding-box size in pixels.
        outline: ear/skull colour, defaults to the amber accent.
        eye: eye colour, defaults to the amber accent over a dark fill.
        nose: muzzle tip colour.
    """
    outline = outline or COLORS["accent"]
    eye = eye or COLORS["accent"]
    nose = nose or COLORS["border_hi"]

    head = _scale(_HEAD_OUTLINE, x, y, size)
    canvas.create_polygon(
        *head,
        fill="",
        outline=outline,
        width=max(1.4, size * 0.055),
        joinstyle="round",
        smooth=False,
    )
    canvas.create_polygon(*_scale(_LEFT_EYE, x, y, size), fill=eye, outline="")
    canvas.create_polygon(*_scale(_RIGHT_EYE, x, y, size), fill=eye, outline="")
    canvas.create_polygon(*_scale(_NOSE, x, y, size), fill=nose, outline="")


def draw_paw(canvas, x: float, y: float, size: float, color: str = None) -> None:
    """Draw a small paw print, used as a bullet in status text."""
    color = color or COLORS["text_dim"]
    pad_w = size * 0.62
    pad_h = size * 0.52
    canvas.create_oval(
        x - pad_w / 2,
        y - pad_h / 2 + size * 0.14,
        x + pad_w / 2,
        y + pad_h / 2 + size * 0.14,
        fill=color,
        outline="",
    )
    toe_r = size * 0.13
    for index, offset in enumerate((-0.36, 0.0, 0.36)):
        toe_x = x + offset * size
        toe_y = y - size * 0.26 + (0.06 if index == 1 else 0.0)
        canvas.create_oval(
            toe_x - toe_r,
            toe_y - toe_r,
            toe_x + toe_r,
            toe_y + toe_r,
            fill=color,
            outline="",
        )


class WolfMark:
    """A canvas holding one wolf head, sized for a header or sidebar."""

    def __init__(self, master, size: int = 40, color: str = None, background: str = None) -> None:
        import tkinter as tk

        self.size = size
        self.canvas = tk.Canvas(
            master,
            width=size,
            height=size,
            highlightthickness=0,
            bd=0,
            bg=background or COLORS["surface"],
        )
        draw_wolf_head(self.canvas, size / 2, size / 2, size * 0.86, outline=color)

    def grid(self, **kwargs) -> None:
        self.canvas.grid(**kwargs)

    def pack(self, **kwargs) -> None:
        self.canvas.pack(**kwargs)

    def place(self, **kwargs) -> None:
        self.canvas.place(**kwargs)
