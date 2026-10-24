"""Cover art from coloured half blocks ("▀": top pixel = foreground, bottom pixel = background).

Pure Rich rendering: no terminal capability queries, so nothing can leak into the input stream, it starts
instantly and works in every true-colour terminal (Windows Terminal, iTerm2, kitty, GNOME, Steam Deck Konsole).
"""
from __future__ import annotations

from PIL import Image
from rich.color import Color
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widget import Widget


def half_block_rows(img, width: int, height: int) -> list[list[Segment]]:
    """PIL image -> `height` rows of `width` cells (2 vertical pixels per cell), aspect ratio kept."""
    img = img.convert("RGB")
    w, h = img.size
    cell_aspect = 2.0                                   # terminal cells are ~2x taller than wide
    target_w = max(1, width)
    target_h = max(2, int(round(target_w * h / w / cell_aspect)) * 2)
    if target_h > height * 2:                            # too tall for the box: fit by height instead
        target_h = height * 2
        target_w = max(1, int(round(target_h * w / h * cell_aspect / 2)))
    small = img.resize((target_w, target_h), resample=Image.Resampling.LANCZOS)
    px = small.load()
    rows = []
    for y in range(0, target_h, 2):
        row = []
        for x in range(target_w):
            top, bottom = px[x, y], px[x, y + 1] if y + 1 < target_h else px[x, y]
            row.append(Segment("▀", Style(color=Color.from_rgb(*top), bgcolor=Color.from_rgb(*bottom))))
        rows.append(row)
    return rows


class HalfBlockCover(Widget):
    """Drop-in for textual-image's widget: assign `.image = PIL.Image` to display it."""

    DEFAULT_CSS = "HalfBlockCover { height: 12; width: 1fr; }"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._image = None
        self._rows: list[list[Segment]] = []
        self._drawn_for = (0, 0)

    @property
    def image(self):
        return self._image

    @image.setter
    def image(self, value) -> None:
        self._image = value
        self._drawn_for = (0, 0)
        self.refresh()

    def render_line(self, y: int) -> Strip:
        width, height = self.size.width, self.size.height
        if self._image is None or width <= 0:
            return Strip.blank(width)
        if self._drawn_for != (width, height):
            self._rows = half_block_rows(self._image, width, height)
            self._drawn_for = (width, height)
        if y >= len(self._rows):
            return Strip.blank(width)
        row = self._rows[y]
        pad = width - len(row)
        return Strip(row + ([Segment(" " * pad)] if pad > 0 else []), width)
