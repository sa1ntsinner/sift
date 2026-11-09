"""The deal list: rows are drawn only when they are on screen.

Textual's DataTable measures every cell of every row it is given, so filling a few thousand deals took most of a
second on every sort, filter and search keystroke. Here a refill is a list swap and the cost of a frame is the height
of the window, whatever the length of the list."""
from __future__ import annotations

from typing import Callable

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip

from .theme import MUTED

CURSOR_BG = "#1c1c1c"
HOVER_BG = "#0b0b0b"


class DealList(ScrollView, can_focus=True):
    """A header line and one line per row. A click previews a row; Enter or a double click opens it."""

    DEFAULT_CSS = """
    DealList { height: 1fr; background: $background; padding: 0 0 0 1; scrollbar-size-vertical: 1;
               scrollbar-size-horizontal: 0; scrollbar-background: $background; scrollbar-color: $panel;
               scrollbar-color-hover: $foreground 30%; scrollbar-color-active: $foreground 40%; }
    """
    BINDINGS = [
        Binding("up", "move(-1)", show=False),
        Binding("down", "move(1)", show=False),
        Binding("pageup", "page(-1)", show=False),
        Binding("pagedown", "page(1)", show=False),
        Binding("home", "end(0)", show=False),
        Binding("end", "end(1)", show=False),
        Binding("enter", "select", show=False),
    ]

    class Highlighted(Message):
        def __init__(self, table: "DealList") -> None:
            super().__init__()
            self.table = table

    class Selected(Message):
        def __init__(self, table: "DealList") -> None:
            super().__init__()
            self.table = table

    class HeaderClicked(Message):
        def __init__(self, table: "DealList", column: str) -> None:
            super().__init__()
            self.table = table
            self.column = column

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.columns: list[tuple[str, Text, int | None]] = []     # (key, label, width; None = takes what is left)
        self.keys: list[str] = []
        self.cursor_row = 0
        self._hover = -1
        self._cells: Callable[[int], list[Text]] = lambda index: []
        self._cache: dict[int, list[Text]] = {}
        self._strips: dict[tuple, Strip] = {}
        self._index: dict[str, int] | None = None

    # ---------------------------------------------------------------- content

    def set_columns(self, columns: list[tuple[str, Text, int | None]]) -> None:
        self.columns = columns
        self._cache.clear()
        self._strips.clear()
        self.refresh()

    def set_rows(self, keys: list[str], cells: Callable[[int], list[Text]], keep: str | None = None) -> None:
        """Swap the list. `cells(index)` builds one row's cells when it first scrolls into view.
        The cursor stays on the row with key `keep` when it is still there, else goes to the top."""
        self.keys, self._cells = keys, cells
        self._cache.clear()
        self._strips.clear()
        self._index = None
        self.virtual_size = Size(self.size.width, len(keys) + 1)
        row = self.index_of(keep) if keep is not None else -1
        self._hover = -1
        self.cursor_row = max(0, row)
        if row < 0:
            self.scroll_to(y=0, animate=False, immediate=True)
        self._show_cursor()
        self.refresh()
        self.post_message(self.Highlighted(self))

    def index_of(self, key: str | None) -> int:
        if self._index is None:
            self._index = {k: n for n, k in enumerate(self.keys)}
        return self._index.get(key, -1) if key is not None else -1

    @property
    def row_count(self) -> int:
        return len(self.keys)

    @property
    def cursor_key(self) -> str | None:
        return self.keys[self.cursor_row] if 0 <= self.cursor_row < len(self.keys) else None

    def get_row_at(self, index: int) -> list[Text]:
        row = self._cache.get(index)
        if row is None:
            if len(self._cache) > 400:
                self._cache.clear()
            row = self._cache[index] = self._cells(index)
        return row

    # ---------------------------------------------------------------- drawing

    def _widths(self) -> list[int]:
        total = self.scrollable_content_region.width
        fixed = sum(w + 2 for _, _, w in self.columns if w is not None)
        return [w if w is not None else max(8, total - fixed - 2) for _, _, w in self.columns]

    def _line(self, cells: list[Text], background: str = "") -> Text:
        line = Text(no_wrap=True, overflow="crop")
        for cell, width in zip(cells, self._widths()):
            cell = cell.copy()
            cell.truncate(width, overflow="ellipsis")
            gap = width - cell.cell_len
            line.append(" " * (1 + (gap if cell.justify == "right" else 0)))
            line.append_text(cell)
            line.append(" " * (1 + (0 if cell.justify == "right" else gap)))
        if background:
            line.stylize_before(Style(bgcolor=background))
        return line

    def render_line(self, y: int) -> Strip:
        width = self.scrollable_content_region.width
        index = round(self.scroll_offset.y) + y - 1 if y else -1
        if y and not 0 <= index < len(self.keys):
            return Strip.blank(width, self.rich_style)
        background = CURSOR_BG if index == self.cursor_row else HOVER_BG if index == self._hover else ""
        key = (index, background, width)
        strip = self._strips.get(key)
        if strip is None:
            base = self.rich_style
            if y == 0:
                line = self._line([label for _, label, _ in self.columns])
                line.stylize_before(Style(color=MUTED))
            else:
                line = self._line(self.get_row_at(index), background)
            segments = [Segment(text, base + style if style else base) for text, style, _ in
                        line.render(self.app.console)]
            fill = base + Style(bgcolor=background) if background else base
            if len(self._strips) > 600:
                self._strips.clear()
            strip = self._strips[key] = Strip(segments).adjust_cell_length(width, fill)
        return strip

    def on_resize(self) -> None:
        self.virtual_size = Size(self.size.width, len(self.keys) + 1)
        self._show_cursor()

    # ---------------------------------------------------------------- cursor

    def _show_cursor(self) -> None:
        height = self.scrollable_content_region.height
        if height <= 1:
            return
        top = round(self.scroll_offset.y)
        if self.cursor_row < top:
            self.scroll_to(y=self.cursor_row, animate=False, immediate=True)
        elif self.cursor_row > top + height - 2:
            self.scroll_to(y=self.cursor_row + 2 - height, animate=False, immediate=True)

    def move_cursor(self, row: int) -> None:
        if not self.keys:
            return
        row = max(0, min(len(self.keys) - 1, row))
        if row != self.cursor_row:
            self.cursor_row = row
            self._show_cursor()
            self.refresh()
            self.post_message(self.Highlighted(self))

    def action_move(self, d: int) -> None:
        self.move_cursor(self.cursor_row + d)

    def action_page(self, d: int) -> None:
        self.move_cursor(self.cursor_row + d * max(1, self.scrollable_content_region.height - 2))

    def action_end(self, last: int) -> None:
        self.move_cursor(len(self.keys) - 1 if last else 0)

    def action_select(self) -> None:
        if self.keys:
            self.post_message(self.Selected(self))

    # ---------------------------------------------------------------- mouse

    def _row_under(self, y: int) -> int:
        index = round(self.scroll_offset.y) + y - 1
        return index if y > 0 and 0 <= index < len(self.keys) else -1

    def on_mouse_move(self, event: events.MouseMove) -> None:
        row = self._row_under(event.y)
        if row != self._hover:
            self._hover = row
            self.refresh()

    def on_leave(self) -> None:
        if self._hover != -1:
            self._hover = -1
            self.refresh()

    def on_click(self, event: events.Click) -> None:
        if event.button != 1:
            return
        event.stop()
        self.focus()
        if event.y == 0:
            x = event.x - 1          # the left padding
            for (key, _, _), width in zip(self.columns, self._widths()):
                if x < width + 2:
                    self.post_message(self.HeaderClicked(self, key))
                    return
                x -= width + 2
            return
        row = self._row_under(event.y)
        if row >= 0:
            self.move_cursor(row)
            if event.chain == 2:
                self.action_select()


__all__ = ["DealList"]
