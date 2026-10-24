"""sift's one theme: pure black, white type, colour only where it means something (the verdict)."""
from textual.theme import Theme

INK = "#f2f2f2"       # titles, prices, names
MUTED = "#8c8c8c"     # secondary facts
DIM = "#4a4a4a"       # empty cells, inactive marks
VERDICT = {
    "hot": "#ff4fa8",       # rare price: grab it
    "great": "#2bff88",     # record price that comes back
    "ok": "#c9c9c9",        # an ordinary discount
    "meh": "#ffd60a",       # it has been a bit cheaper / big sale soon
    "nope": "#ff5a1f",      # much cheaper before / fake discount
    "family": "#6e9cff",    # already in your Steam Family
    "wish": "#ff4fa8",      # wishlist mark
}
ACCENT = "#2bff88"

SIFT = Theme(
    name="sift",
    primary=ACCENT,
    secondary=VERDICT["meh"],
    accent=ACCENT,
    warning=VERDICT["meh"],
    error=VERDICT["nope"],
    success=ACCENT,
    foreground=INK,
    background="#000000",
    surface="#0b0b0b",
    panel="#1c1c1c",
    dark=True,
)

THEMES = [SIFT]

BASE_CSS = """
Screen { background: $background; }
.title { text-style: bold; color: $foreground; }
.muted { color: $foreground 60%; }
.ok { color: $success; }
.bad { color: $error; }
.warn { color: $warning; }
Button { min-width: 12; }
Input { border: tall $panel; }
Input:focus { border: tall $primary; }
Toast { background: $panel; border-left: none; padding: 0 2; }
Toast > .toast--title { text-style: bold; }
"""
