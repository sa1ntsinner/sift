"""The full-screen app that plain `sift` opens.

One header line (tabs + what the list shows), one table, one details pane, one line of keys.
Everything works from the keyboard; every key is listed under `?`."""
from __future__ import annotations

import importlib
import sqlite3
import time
import webbrowser
from dataclasses import replace

from rich.text import Text
from rich.style import Style
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import ContentSwitcher, DataTable, Input, LoadingIndicator, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import get_current_worker

from .. import config, engine, net, prefs, query as qry
from ..i18n import date, num, t
from ..recommender import Rec, Verdict, short_name, verdict as judge
from ..steam import Item
from .theme import ACCENT, BASE_CSS, INK, MUTED, DIM, VERDICT, THEMES
from .state import Data, REFRESH_AFTER, load_snapshot, save_snapshot

SORTS = list(qry.SORTS)
TABS = ("picks", "wish", "discover", "dlc")
TAB_LABEL = {"picks": "tu_tab_deals", "wish": "tu_tab_wish", "discover": "tu_tab_discover", "dlc": "tu_tab_dlc"}
DEAL_TABS = ("picks", "wish", "discover")
WORTH_TABS = ("picks", "discover")        # open on HOT + GREAT only; the wishlist and DLC show every verdict
WORTH = ("hot", "great")


class Loader:
    """Real data source; tests pass a stub with the same `load()` / `load_dlc()`.

    `stale=True` builds from whatever is cached — even expired — so the app paints instantly;
    the app then calls `load(stale=False)` in the background and swaps in fresh data.
    The whole pool is loaded (no discount / price floor): the app's filters decide what is shown.
    """

    def load(self, progress=lambda key: None, stale: bool = False) -> Data:
        from ..db import db, set_stale_ok
        if stale:
            saved = load_snapshot()
            if saved is not None:
                return saved
        set_stale_ok(stale)
        failures = net.steam_failures()
        try:
            progress("sp_library")
            ctx = engine.Context(engine.search_many(engine.BASE_PAGES))
            if stale and not (ctx.candidates or ctx.wish_items):
                raise LookupError("No saved results yet")
            db().flush()
            ctx.with_family = True             # always loaded; the family switch filters them live
            progress("sp_sift")
            ctx.load_pool()
            progress("sp_discover")
            ctx.load_discovery_pool()
            if not stale and net.steam_failures() != failures:
                raise RuntimeError(t("tu_network_failed"))
            if not stale:
                set_stale_ok(True)
                try:
                    preview = Data(ctx, engine.build_digest(ctx, limit=60, min_discount=0, budget=0,
                                                           discover=True, history_all=True),
                                   saved_at=time.time(), complete=False)
                finally:
                    set_stale_ok(False)
                previous = load_snapshot()
                if previous:
                    preview.dlc, preview.dlc_at = previous.dlc, previous.dlc_at
                save_snapshot(preview)
                progress(preview)
            progress("sp_history")
            data = Data(ctx, engine.build_digest(ctx, limit=60, min_discount=0, budget=0, discover=True,
                                                 history_all=True), saved_at=0 if stale else time.time())
            if not stale and net.steam_failures() != failures:
                raise RuntimeError(t("tu_network_failed"))
            if not stale:
                previous = load_snapshot()
                if previous:
                    data.dlc, data.dlc_at = previous.dlc, previous.dlc_at
                save_snapshot(data)
            return data
        finally:
            set_stale_ok(False)

    def load_dlc(self) -> list:
        failures = net.steam_failures()
        rows = engine.dlc_rows(limit=60, min_discount=0, budget=0)[0][:120]
        if net.steam_failures() != failures:
            raise RuntimeError(t("tu_network_failed"))
        return rows


def verdict_of(row) -> Verdict:
    """Rec carries its verdict; DLC rows get one computed from their history."""
    v = getattr(row, "verdict", None)
    if isinstance(v, Verdict):
        return v
    return judge(row.item.cut, row.hist)


def worth_it(row) -> bool:
    return verdict_of(row).kind in WORTH or bool(getattr(row, "extras", {}).get("target", {}).get("hit"))


def verdict_cell(v: Verdict) -> Text:
    if not v.kind:
        return Text("·", style=DIM)
    if v.kind == "ok":                    # the ordinary case stays quiet so the others stand out
        return Text(t("vd_ok"), style=MUTED)
    return Text(t(f"vd_{v.kind}"), style=f"bold {VERDICT[v.kind]}")


# --------------------------------------------------------------------------- side panel: filters, saved, hidden

PANEL_CSS = """
{name} { align: right top; background: $background 55%; }
{name} #panel { width: 52; max-width: 100%; height: 100%; padding: 1 2; background: $surface; }
{name} .head { height: 1; margin-bottom: 1; }
{name} OptionList { height: 1fr; border: none; padding: 0; background: $surface; scrollbar-size-vertical: 1; }
{name} OptionList:focus { border: none; }
{name} OptionList > .option-list--option-highlighted { background: $panel; text-style: none; }
{name} OptionList:focus > .option-list--option-highlighted { background: $panel; text-style: none; }
{name} #edit { display: none; height: 1; border: none; padding: 0 1; margin-top: 1; background: $panel; }
{name} #edit.show { display: block; }
{name} #edit:focus { border: none; }
{name} .foot { height: auto; margin-top: 1; color: $foreground 55%; }
"""

# (shortcut, Query attribute, label key)
SWITCHES = (
    ("a", "buy", "tu_f_buy"),
    ("l", "lowest", "tu_f_lowest"),
    ("y", "low_2y", "tu_f_2y"),
    ("w", "rare", "tu_f_rare"),
    ("b", "bundle", "tu_f_bundle"),
    ("d", "deck", "tu_f_deck"),
    ("n", "my_lang", "tu_f_lang"),
    ("e", "no_ea", "tu_f_no_ea"),
    ("m", "family", "tu_f_family"),
)
# (shortcut, field, label key)
LIMITS = (
    ("p", "price", "tu_f_price"),
    ("c", "cut", "tu_f_cut"),
    ("r", "rating", "tu_f_rating"),
    ("t", "tags", "tu_f_tags"),
    ("T", "no_tags", "tu_f_no_tags"),
)


def _row(key: str, label: str, value: Text | str = "", on: bool | None = None) -> Text:
    line = Text()
    line.append(f" {key} ", style=f"bold {INK}")
    line.append(" ")
    if on is not None:
        line.append("● " if on else "○ ", style=f"bold {ACCENT}" if on else DIM)
    line.append(label, style=INK)
    if value:
        pad = max(1, 34 - len(line.plain))
        line.append(" " * pad)
        line.append_text(value if isinstance(value, Text) else Text(str(value), style=MUTED))
    return line


def _heading(label: str) -> Option:
    return Option(Text(label, style=f"bold {MUTED}"), disabled=True)


def panel_title(key: str) -> Text:
    title = Text(t(key), style=f"bold {INK}")
    title.append("   ×", style=Style(color=MUTED, meta={"@click": "screen.close"}))
    return title


class FilterPanel(ModalScreen[None]):
    """Filters, saved filter sets and hidden games in one place. Every change applies at once."""
    CSS = PANEL_CSS.replace("{name}", "FilterPanel")
    BINDINGS = [Binding("escape", "close", show=False), Binding("f", "close", show=False)]

    def __init__(self, app_view):
        super().__init__()
        self.host = app_view            # the SiftApp: reads and sets its view
        self.editing: str = ""
        self._keys: dict[str, str] = {}

    # ---------------------------------------------------------------- building

    def compose(self) -> ComposeResult:
        with Vertical(id="panel"):
            yield Static(panel_title("tu_filters"), classes="head")
            yield OptionList(id="opts", compact=True)
            yield Input(id="edit", compact=True)
            yield Static(Text(t("tu_filters_foot")), classes="foot")

    def on_mount(self) -> None:
        self.rebuild()
        self.query_one("#opts", OptionList).focus()

    def _value(self, fld: str) -> str:
        q = self.host.view
        if fld == "price":
            cap = q.price_cap()
            return f"{cap:g}" if cap else t("tu_any")
        if fld == "cut":
            return f"{q.cut_floor()}%"
        if fld == "rating":
            return f"{q.min_rating}%" if q.min_rating else t("tu_any")
        if fld == "tags":
            return ", ".join(q.tags) or "—"
        return ", ".join(q.no_tags) or "—"

    def rebuild(self) -> None:
        from ..cli import describe
        q = self.host.view
        ol = self.query_one("#opts", OptionList)
        keep = ol.highlighted
        ol.clear_options()
        self._keys = {}
        opts: list[Option] = [_heading(t("tu_f_show"))]
        for key, attr, label in SWITCHES:
            on = q.shows_family() if attr == "family" else bool(getattr(q, attr))
            opts.append(Option(_row(key, t(label), on=on), id=f"sw:{attr}"))
            self._keys[key] = f"sw:{attr}"
        opts.append(_heading(t("tu_f_limits")))
        for key, fld, label in LIMITS:
            opts.append(Option(_row(key, t(label), self._value(fld)), id=f"ed:{fld}"))
            self._keys[key] = f"ed:{fld}"
        opts.append(_heading(t("tu_f_saved")))
        macros = sorted(qry.all_macros().items(), key=lambda kv: (kv[1][1], kv[0]))
        for n, (name, (flags, builtin)) in enumerate(macros[:9], start=1):
            try:
                what = describe(qry.parse(flags))
            except qry.QueryError as e:
                what = f"✗ {e}"
            active = name in q.macros
            line = Text.assemble((f" {n} ", f"bold {INK}"), "  ",
                                 (name, f"bold {ACCENT}" if active else INK),
                                 " " * max(1, 12 - len(name)), (short_name(what, 26), MUTED))
            opts.append(Option(line, id=f"mc:{name}"))
            self._keys[str(n)] = f"mc:{name}"
        opts.append(Option(_row("s", t("tu_f_save")), id="do:save"))
        self._keys["s"] = "do:save"
        opts.append(Option(_row("h", t("tu_f_hidden"), str(len(prefs.load_hidden()))), id="do:hidden"))
        self._keys["h"] = "do:hidden"
        opts.append(Option(_row("0", t("tu_f_reset")), id="do:reset"))
        self._keys["0"] = "do:reset"
        ol.add_options(opts)
        if keep is not None and keep < ol.option_count:
            ol.highlighted = keep
        else:
            ol.highlighted = 1

    # ---------------------------------------------------------------- actions

    def run(self, oid: str) -> None:
        kind, _, arg = oid.partition(":")
        q = self.host.view
        if kind == "sw":
            now = q.shows_family() if arg == "family" else getattr(q, arg)
            self.host.set_view(replace(q, macros=[], **{arg: not now}))
        elif kind == "mc":
            self.host.apply_macro(arg)
        elif kind == "ed":
            self._start_edit(arg)
            return
        elif arg == "save":
            self._start_edit("save")
            return
        elif arg == "hidden":
            self.app.push_screen(HiddenPanel(), lambda _: (self.host.refill(), self.rebuild()))
            return
        elif arg == "reset":
            self.host.set_view(qry.Query(tab=q.tab, sort=q.sort))
        self.rebuild()

    def _start_edit(self, what: str) -> None:
        self.editing = what
        box = self.query_one("#edit", Input)
        prompts = {"save": t("tu_f_save_ph"), **{fld: t(lbl) for _, fld, lbl in LIMITS}}
        box.placeholder = prompts.get(what, "")
        box.value = "" if what in ("save",) else self._raw(what)
        box.add_class("show")
        box.focus()

    def _raw(self, fld: str) -> str:
        q = self.host.view
        return {"price": "" if q.max_price is None else f"{q.max_price:g}",
                "cut": "" if q.min_cut is None else str(q.min_cut),
                "rating": str(q.min_rating or ""),
                "tags": ", ".join(q.tags), "no_tags": ", ".join(q.no_tags)}[fld]

    def _stop_edit(self) -> None:
        self.editing = ""
        box = self.query_one("#edit", Input)
        box.remove_class("show")
        box.value = ""
        self.query_one("#opts", OptionList).focus()

    @on(Input.Submitted, "#edit")
    def edited(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        what = self.editing
        q = replace(self.host.view, macros=[])
        try:
            if what == "save":
                if raw:
                    self.host.save_macro(raw, q)
            elif what == "price":
                q.max_price = float(raw.replace(",", ".").lstrip("$")) if raw else None
            elif what == "cut":
                q.min_cut = int(raw.rstrip("%")) if raw else None
                if q.min_cut is not None and not 0 <= q.min_cut <= 100:
                    raise qry.QueryError(t("q_bad_cut"))
            elif what == "rating":
                q.min_rating = int(raw.rstrip("%")) if raw else 0
            elif what == "tags":
                q.tags = [qry.resolve_tags(x) for x in raw.split(",") if x.strip()]
            elif what == "no_tags":
                q.no_tags = [qry.resolve_tag(x) for x in raw.replace("|", ",").split(",") if x.strip()]
        except (ValueError, qry.QueryError) as e:
            self.notify(t("ui_f_bad", err=e), severity="error", timeout=5)
            return
        if what != "save":
            self.host.set_view(q)
        self._stop_edit()
        self.rebuild()

    @on(OptionList.OptionSelected, "#opts")
    def chosen(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.run(event.option.id)

    def on_key(self, event: events.Key) -> None:
        if self.editing:
            if event.key == "escape":
                event.stop()
                self._stop_edit()
            return
        ol = self.query_one("#opts", OptionList)
        key = event.character if event.character and event.character.isprintable() else event.key
        if key in ("j", "k"):
            event.stop()
            ol.action_cursor_down() if key == "j" else ol.action_cursor_up()
            return
        if key == "space" and ol.highlighted is not None:
            event.stop()
            oid = ol.get_option_at_index(ol.highlighted).id
            if oid:
                self.run(oid)
            return
        if key in self._keys:
            event.stop()
            oid = self._keys[key]
            ol.highlighted = next(i for i in range(ol.option_count) if ol.get_option_at_index(i).id == oid)
            self.run(oid)

    def action_close(self) -> None:
        if self.editing:
            self._stop_edit()
            return
        self.dismiss(None)


class HiddenPanel(ModalScreen[None]):
    """Games you hid. Enter or x brings one back."""
    CSS = PANEL_CSS.replace("{name}", "HiddenPanel")
    BINDINGS = [Binding("escape", "close", show=False), Binding("h", "close", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="panel"):
            yield Static(panel_title("tu_hidden_title"), classes="head")
            yield OptionList(id="opts", compact=True)
            yield Static(Text(t("tu_hidden_foot")), classes="foot")

    def on_mount(self) -> None:
        self.rebuild()
        self.query_one("#opts", OptionList).focus()

    def rebuild(self) -> None:
        ol = self.query_one("#opts", OptionList)
        ol.clear_options()
        hidden = prefs.load_hidden()
        if not hidden:
            ol.add_option(Option(Text(t("tu_hidden_none"), style=MUTED), disabled=True))
            return
        for appid, h in sorted(hidden.items(), key=lambda kv: -kv[1].get("at", 0)):
            why = t("reason_taste") if h.get("reason") == "taste" else t("reason_owned")
            line = Text(short_name(h["name"], 30), style=INK)
            line.append(" " * max(1, 32 - len(line.plain)))
            line.append(f"{why} · {date(h['at'])}", style=MUTED)
            ol.add_option(Option(line, id=str(appid)))
        ol.highlighted = 0

    def _restore(self) -> None:
        ol = self.query_one("#opts", OptionList)
        if ol.highlighted is None:
            return
        oid = ol.get_option_at_index(ol.highlighted).id
        if oid and oid.isdigit():
            name = prefs.load_hidden().get(int(oid), {}).get("name", oid)
            prefs.unhide(int(oid))
            self.notify(t("restored", name=name), timeout=3)
            self.rebuild()

    @on(OptionList.OptionSelected, "#opts")
    def chosen(self) -> None:
        self._restore()

    def on_key(self, event: events.Key) -> None:
        ol = self.query_one("#opts", OptionList)
        if event.key in ("j", "k"):
            event.stop()
            ol.action_cursor_down() if event.key == "j" else ol.action_cursor_up()
        elif event.key in ("x", "u", "delete"):
            event.stop()
            self._restore()

    def action_close(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    """Every key on one page (`?`)."""
    CSS = PANEL_CSS.replace("{name}", "HelpScreen") + """
    HelpScreen #panel { width: 66; }
    HelpScreen VerticalScroll { height: 1fr; }
    """
    BINDINGS = [
        Binding("escape,question_mark,q,enter", "close", show=False),
        Binding("j,down", "scroll(1)", show=False),
        Binding("k,up", "scroll(-1)", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="panel"):
            yield Static(panel_title("tu_help_title"), classes="head")
            with VerticalScroll(id="help"):
                yield Static(help_text())

    def on_mount(self) -> None:
        self.query_one("#help").focus()

    def action_scroll(self, d: int) -> None:
        box = self.query_one("#help", VerticalScroll)
        box.scroll_down(animate=False) if d > 0 else box.scroll_up(animate=False)

    def action_close(self) -> None:
        self.dismiss(None)


HELP = (
    ("tu_h_move", (("↑ ↓  j k", "tu_h_rows"), ("g  G", "tu_h_ends"), ("1–4  ← →  tab", "tu_h_tabs"))),
    ("tu_h_game", (("enter  o", "tu_h_open"), ("i", "tu_h_itad"), ("b", "tu_h_bundle"),
                   ("x", "tu_h_hide"), ("X", "tu_h_own"), ("u", "tu_h_undo"))),
    ("tu_h_list", (("a", "tu_h_all"), ("d", "tu_h_details"), ("/", "tu_h_search"), ("f", "tu_h_filters"), ("s  S", "tu_h_sort"), ("0", "tu_h_reset"),
                   ("r", "tu_h_refresh"))),
    ("tu_h_app", (("?", "tu_h_help"), ("q", "tu_h_quit"))),
)


def help_text() -> Text:
    out = Text()
    for title, rows in HELP:
        out.append(t(title) + "\n", style=f"bold {MUTED}")
        for keys, label in rows:
            out.append(f"  {keys:<15}", style=f"bold {INK}")
            out.append(t(label) + "\n", style=INK)
        out.append("\n")
    out.append(t("tu_help_verdicts") + "\n", style=f"bold {MUTED}")
    for kind in ("hot", "great", "ok", "meh", "nope"):
        out.append(f"  {t('vd_' + kind):<15}", style=f"bold {VERDICT[kind]}")
        out.append(t(f"tu_v_{kind}") + "\n", style=INK)
    return out


# --------------------------------------------------------------------------- details pane

BARS = " ▁▂▃▄▅▆▇█"


def sale_bars(hist, width: int, colour: str) -> Text:
    """Two years of Steam sales in `width` cells: each cell shows the deepest cut in its slice of time."""
    import datetime as dt
    out = Text()
    if not hist or not hist.points:
        return out
    today = dt.date.today()
    start = today - dt.timedelta(days=730)
    span = 730 / width
    cells = [0] * width
    pts = [(dt.date.fromisoformat(d), c) for d, c in hist.points]
    for i, (day, cut) in enumerate(pts):
        end = pts[i + 1][0] if i + 1 < len(pts) else today
        if cut <= 0:
            continue
        a = max(0, int((day - start).days / span))
        b = min(width - 1, int(max(0, (end - start).days - 1) / span))
        for c in range(a, b + 1):
            cells[c] = max(cells[c], cut)
    best = max(hist.best_cut, 1)
    for cut in cells:
        if cut <= 0:
            out.append("▁", style=DIM)
        else:
            ch = BARS[max(1, round(8 * cut / best))]          # relative to its record: depth differences show
            out.append(ch, style=colour if cut >= best else MUTED)
    return out


def render_details(row, status: str = "", width: int = 44) -> Text:
    """The game, its price, the verdict with its reason, two years of sales, then everything else."""
    from ..notify.cards import notes_for
    i: Item = row.item
    v = verdict_of(row)
    colour = VERDICT.get(v.kind, INK)
    out = Text()
    out.append(i.name + "\n", style=f"bold {INK}")
    meta = [x for x in (i.developers[0] if i.developers else "",
                        time.strftime("%Y", time.localtime(i.release)) if i.release else "",
                        {3: "Deck ✓", 2: "Deck ~"}.get(i.deck, "")) if x]
    if meta:
        out.append(" · ".join(meta) + "\n", style=MUTED)
    out.append("\n")

    if not i.available:
        out.append(t("st_unavailable", country=engine.country_name()) + "\n", style=f"bold {VERDICT['nope']}")
    elif i.purchasable:
        out.append(i.final_fmt, style=f"bold {INK}")
        if i.cut:
            out.append(f"  {i.orig_fmt}", style=f"strike {MUTED}")
            out.append(f"  −{i.cut}%", style=f"bold {INK}")
        if i.ends_at and i.ends_at > time.time():
            ends = engine_days(i.ends_at)
            line = len(out.plain) - out.plain.rfind("\n") - 1
            out.append(f"   {ends}" if line + 3 + len(ends) <= width else f"\n{ends}", style=MUTED)
        out.append("\n")

    if v.kind:
        out.append("\n" + t(f"vd_{v.kind}") + "\n", style=f"bold {colour}")
        out.append(t(f"vr_{v.reason}", n=v.value) + "\n", style=INK)

    h = row.hist
    if h and h.covered_days and not h.sales_2y:
        out.append("\n" + t("tu_first_sale" if i.cut > 0 else "tu_no_sales") + "\n", style=MUTED)
    elif h and h.points:
        out.append("\n")
        bars = max(16, width - 2)
        out.append_text(sale_bars(h, bars, colour))
        ago, now = t("tu_2y_ago"), t("tu_now")
        out.append("\n" + ago + " " * max(1, bars - len(ago) - len(now)) + now + "\n", style=DIM)
        line = t("tu_sales_2y", n=h.sales_2y)
        if h.gap_days:
            line += ", " + t("tu_every", n=h.gap_days)
        out.append(line + "\n", style=MUTED)
        cuts = [t("tu_usually", n=h.typical_cut)] if h.typical_cut else []
        if h.best_cut:
            cuts.append(t("tu_best", n=h.best_cut))
        if cuts:
            out.append(" · ".join(cuts) + "\n", style=MUTED)
        if h.since_last_days and i.cut <= 0:
            out.append(t("tu_since_last", n=h.since_last_days) + "\n", style=MUTED)
    elif h and h.best_cut:
        out.append("\n" + t("tu_best", n=h.best_cut) + "\n", style=MUTED)

    out.append("\n")
    if i.review_count:
        out.append(t("reviews_of", pct=i.review_pct, n=num(i.review_count)) + "\n", style=INK)
    if status:
        out.append(status + "\n", style=VERDICT["family"])
    why = getattr(row, "why", "")
    if why:
        out.append(why + "\n", style=MUTED)
    if isinstance(row, Rec):
        notes = notes_for(row)
        if notes:
            out.append(notes + "\n", style=MUTED)
    base = getattr(row, "base_name", "")
    if base:
        out.append(t("tu_dlc_for", name=base) + "\n", style=MUTED)
    return out


def engine_days(ts: int) -> str:
    secs = ts - time.time()
    return t("tu_ends_h", n=max(1, round(secs / 3600))) if secs < 86400 else t("tu_ends_d", n=round(secs / 86400))


class Details(VerticalScroll):
    DEFAULT_CSS = """
    Details { width: 48; padding: 0 2 0 3; background: $background; }
    Details #cover { height: 10; margin-bottom: 1; }
    Details.pixels #cover { width: 100%; height: auto; max-height: 12; }
    """

    def __init__(self, images: bool | str, **kw):
        super().__init__(**kw)
        self.mode = cover_mode(images)
        self.images = self.mode != "off"
        self._appid = 0

    def compose(self) -> ComposeResult:
        if self.images:
            if self.mode in ("sixel", "tgp"):
                self.add_class("pixels")
            try:
                yield image_widget(self.mode)(id="cover")
            except Exception:  # noqa: BLE001 - terminals without image support just skip the cover
                self.images = False
        yield Static(id="info")

    def show(self, row, status: str = "") -> None:
        info = self.query_one("#info", Static)
        if row is None:
            info.update(Text(""))
            return
        self._appid = row.item.appid
        info.update(render_details(row, status, max(30, self.size.width - 5 or 44)))
        if self.images:
            self.fetch_cover(row.item.appid, row.item.cover)

    @work(thread=True, exclusive=True, group="cover")
    def fetch_cover(self, appid: int, url: str) -> None:
        from PIL import Image as PILImage
        from ..net import SESSION
        folder = config.STATE_DIR / "covers"
        folder.mkdir(exist_ok=True)
        path = folder / f"{appid}.jpg"
        if not path.exists():
            try:
                r = SESSION.get(url, timeout=10)
                if r.status_code != 200:
                    return
                path.write_bytes(r.content)
            except Exception:  # noqa: BLE001
                return
        try:
            img = PILImage.open(path)
            img.load()
        except Exception:  # noqa: BLE001
            return
        if self._appid == appid:
            self.app.call_from_thread(self._set_cover, img)

    def _set_cover(self, img) -> None:
        try:
            self.query_one("#cover").image = img
        except Exception:  # noqa: BLE001
            pass


def cover_mode(images: bool | str) -> str:
    """Resolved cover renderer: 'sixel' / 'tgp' (real pixels), 'blocks' (coloured half-cells) or 'off'.

    'auto' needs `probe_covers()` to have run (before Textual starts); without it we stay on 'blocks'."""
    if images is False:
        return "off"
    if images is True:
        images = config.cfg.settings.covers
    if images == "auto":
        return _probed or "blocks"
    return images if images in ("blocks", "sixel", "tgp", "off") else "blocks"


_probed: str | None = None


def probe_covers(setting: str) -> str:
    """Ask the terminal once — before Textual owns stdin — what graphics it supports.

    Windows Terminal ≥ 1.22, foot, mlterm, WezTerm… → Sixel; kitty, Ghostty → TGP; anything else → blocks."""
    global _probed
    if setting not in ("auto", "sixel"):
        return cover_mode(setting)
    try:
        importlib.import_module("textual_image.widget")          # runs the probe at import
        from textual_image._terminal import probe_terminal
        caps = probe_terminal()
    except Exception:  # noqa: BLE001 - no capable terminal (pipes, old consoles): fall back to blocks
        _probed = "blocks"
        return "blocks"
    if setting == "sixel":
        _probed = "sixel"
    else:
        _probed = "tgp" if caps.tgp else "sixel" if caps.sixel else "blocks"
    return _probed


def image_widget(mode: str):
    if mode == "blocks":
        from .cover import HalfBlockCover
        return HalfBlockCover                        # pure Rich: no terminal queries at all
    from textual_image import widget
    return {"sixel": widget.SixelImage, "tgp": widget.TGPImage}.get(mode, widget.HalfcellImage)


# --------------------------------------------------------------------------- app

class DealTable(DataTable):
    """A click previews a game; Enter or a double click opens it."""

    def on_resize(self) -> None:
        game = self.columns.get("game")
        if game is None or not self.content_size.width:
            return
        fixed = sum(c.get_render_width(self) for c in self.ordered_columns if c is not game)
        game.width = max(8, self.content_size.width - fixed - 2 * self.cell_padding - 1)
        game.auto_width = False
        if self.row_count:
            key = self.ordered_rows[0].key
            self.update_cell(key, "game", self.get_cell(key, "game"), update_width=True)

    async def _on_click(self, event: events.Click) -> None:
        event.prevent_default()
        row = event.style.meta.get("row", -1)
        if event.button != 1 or row < 0:
            await super()._on_click(event)
            return
        if row < self.row_count:
            self.move_cursor(row=row, column=event.style.meta.get("column", 0))
            if event.chain == 2:
                self.action_select_cursor()
        event.stop()


class SiftApp(App):
    TITLE = "sift"
    AUTO_FOCUS = None          # never focus a widget implicitly: stray terminal replies must not become typing
    ENABLE_COMMAND_PALETTE = False
    CSS = BASE_CSS + """
    #header { height: 1; padding: 0 2; margin-bottom: 1; }
    #search { display: none; height: 1; margin: 0 2 1 2; border: none; padding: 0 1; background: $panel; }
    #search:focus { border: none; }
    #search.show { display: block; }
    #loading-box { height: 1fr; align: center middle; }
    #loading-box LoadingIndicator { height: 1; width: 100%; }
    #loading-text { width: 100%; text-align: center; }
    #loading-text { margin-top: 1; color: $foreground 60%; }
    #views { height: 1fr; }
    .deals { height: 1fr; }
    DataTable { height: 1fr; background: $background; padding: 0 0 0 1; scrollbar-size-vertical: 1;
                scrollbar-size-horizontal: 0; scrollbar-background: $background; scrollbar-color: $panel;
                scrollbar-color-hover: $foreground 30%; scrollbar-color-active: $foreground 40%; }
    DataTable > .datatable--header { background: $background; color: $foreground 45%; text-style: none; }
    DataTable > .datatable--cursor { background: $panel; text-style: none; }
    DataTable:focus > .datatable--cursor { background: $panel; text-style: none; }
    DataTable > .datatable--hover { background: $surface; }
    #empty { display: none; height: 1fr; padding: 2 3; color: $foreground 60%; }
    #empty.show { display: block; }
    #keys { height: 1; padding: 0 2; }
    Screen.medium Details { width: 38; padding: 0 1 0 2; }
    Screen.narrow Details { display: none; }
    Screen.narrow.details-on Details { display: block; width: 55%; padding: 0 1 0 2; }
    """
    BINDINGS = [
        Binding("a", "everything", show=False),
        Binding("o", "open", show=False),
        Binding("i", "itad", show=False),
        Binding("b", "bundle", show=False),
        Binding("slash", "search", show=False),
        Binding("f", "filters", show=False),
        Binding("s", "sort(1)", show=False),
        Binding("S", "sort(-1)", show=False),
        Binding("x", "hide('taste')", show=False),
        Binding("X", "hide('owned')", show=False),
        Binding("u", "undo", show=False),
        Binding("0", "reset", show=False),
        Binding("r", "refresh", show=False),
        Binding("question_mark", "help", show=False),
        Binding("d", "details", show=False),
        Binding("q", "quit", show=False),
        Binding("escape", "escape", show=False),
        Binding("j", "cursor(1)", show=False),
        Binding("k", "cursor(-1)", show=False),
        Binding("g", "cursor_end(0)", show=False),
        Binding("G", "cursor_end(1)", show=False),
        Binding("left,left_square_bracket,shift+tab", "step_tab(-1)", show=False, priority=True),
        Binding("right,right_square_bracket,tab", "step_tab(1)", show=False, priority=True),
        *[Binding(str(n), f"tab('{tab}')", show=False) for n, tab in enumerate(TABS, 1)],
    ]

    WORTH_IT_FIRST = True      # tests of other features switch this off to see every row

    def __init__(self, loader: Loader | None = None, images: bool = True, query: qry.Query | None = None):
        super().__init__()
        self.loader = loader or Loader()
        self.images = images
        self.data: Data | None = None
        self.recs: dict[str, list] = {tab: [] for tab in TABS}
        self.dlc_loaded = False
        self.undo_stack: list[int] = []
        self.query_text = ""
        self.view = query or qry.Query()
        self.fresh = False
        self.loading = False
        self.refresh_error = ""
        self._dlc_loading = False
        self._retry_at = 0
        self.dlc_error = ""
        self._storage_error = ""
        self._shown: dict[str, int] = {}
        self._all: dict[str, int] = {}
        self.everything = not self.WORTH_IT_FIRST
        self._hidden_cache: set[int] = set()
        self.tab = self.view.tab if self.view.tab in TABS else "picks"

    @property
    def sort(self) -> str:
        return self.view.sort

    def compose(self) -> ComposeResult:
        yield Static(id="header")
        yield Input(placeholder=t("tu_search_ph"), id="search", disabled=True, compact=True)
        with Vertical(id="loading-box"):
            yield LoadingIndicator()
            yield Static(t("sp_library"), id="loading-text")
        with ContentSwitcher(id="views", initial=self.tab):
            for tab in TABS:
                with Horizontal(id=tab, classes="deals"):
                    yield DealTable(id=f"t-{tab}", cursor_type="row", show_row_labels=False, zebra_stripes=False)
                    yield Details(self.images, id=f"d-{tab}")
        yield Static(id="empty")
        yield Static(id="keys")

    def on_mount(self) -> None:
        for th in THEMES:
            self.register_theme(th)
        self.theme = "sift"
        self.query_one("#views").display = False
        self._layout()
        self._header()
        self._keys()
        from ..db import refresh_requested
        self.loading = True
        self.load(refresh=refresh_requested())
        self.set_interval(60, self._refresh_if_due)
        self.set_interval(5, self.checkpoint)

    # ---------------------------------------------------------------- loading

    @work(thread=True, exclusive=True, group="load")
    def load(self, refresh: bool = False) -> None:
        from ..db import set_refresh
        worker = get_current_worker()

        def deliver(callback, *args):
            if not worker.is_cancelled:
                self.call_from_thread(lambda: callback(*args) if not worker.is_cancelled
                                      and self.query("#header") else None)

        progress = lambda key: deliver(self._progress, key)  # noqa: E731
        try:
            if self.data is None:
                try:
                    data = self.loader.load(progress, stale=True)
                    recent = data.complete and 0 <= time.time() - data.saved_at < REFRESH_AFTER
                    deliver(self.populate, data, recent and not refresh)
                    if recent and not refresh:
                        return
                except Exception:  # noqa: BLE001 - fresh load covers missing or unusable cache
                    pass
            data = self.loader.load(progress, stale=False)
            deliver(self.populate, data, True)
        except Exception as e:  # noqa: BLE001
            deliver(self._load_failed, str(e))
        finally:
            set_refresh(False)
            deliver(self._load_finished)

    def _load_finished(self) -> None:
        self.loading = False
        self._header()
        if self.tab == "dlc" and self.data is not None:
            self._request_dlc()

    def _refresh_if_due(self) -> None:
        if self.data and not self.loading and not self._dlc_loading and time.time() >= self._retry_at:
            if not self.data.complete or time.time() - self.data.saved_at >= REFRESH_AFTER:
                self.loading = True
                self.fresh = False
                self._header()
                self.load()
        self._header()

    @work(thread=True, group="checkpoint", exclusive=True)
    def checkpoint(self) -> None:
        from ..db import db
        try:
            db().flush()
        except sqlite3.Error as e:
            if not get_current_worker().is_cancelled:
                self.call_from_thread(self._save_failed, str(e))

    def _save_failed(self, msg: str) -> None:
        if msg != self._storage_error:
            self._storage_error = msg
            self.notify(t("tu_save_failed", err=msg), severity="warning", timeout=8)

    def _progress(self, key: str | Data) -> None:
        if isinstance(key, Data):
            self.populate(key)
        else:
            self.query_one("#loading-text", Static).update(t(key))

    def _load_failed(self, msg: str) -> None:
        self.refresh_error = msg
        self._retry_at = time.time() + 5 * 60
        self.fresh = False
        if self.data is None:
            self.query_one("#loading-text", Static).update(Text(f"✗ {msg}", style=VERDICT["nope"]))
        else:
            self.notify(f"{t('ui_refresh_failed')}: {msg}", severity="warning", timeout=6)
            self._header()

    def populate(self, data: Data, fresh: bool = False) -> None:
        first = self.data is None
        self.data = data
        self.fresh = fresh
        self.refresh_error = ""
        d = data.digest
        self.recs.update({"picks": list(d.picks), "wish": list(d.wish),
                          "discover": list(getattr(d, "discover", []) or [])})
        if data.dlc or data.dlc_at:
            self.recs["dlc"], self.dlc_loaded = list(data.dlc), True
        self.query_one("#loading-box").display = False
        self.query_one("#views").display = True
        self.refill()
        if first:
            self._focus_table()
        if self.tab == "dlc" and not self.loading:
            self._request_dlc()

    def _request_dlc(self, force: bool = False) -> None:
        if self.loading or self._dlc_loading:
            return
        if not force and self.dlc_loaded and self.data and time.time() - self.data.dlc_at < REFRESH_AFTER:
            return
        self._dlc_loading = True
        self.dlc_error = ""
        self._header()
        self.load_dlc(force)

    @work(thread=True, exclusive=True, group="dlc")
    def load_dlc(self, force: bool = False) -> None:
        from ..db import set_refresh
        worker = get_current_worker()
        try:
            if force:
                set_refresh(True)
            rows = self.loader.load_dlc()
        except Exception as e:  # noqa: BLE001
            if not worker.is_cancelled:
                self.call_from_thread(self._dlc_failed, str(e))
        else:
            if not worker.is_cancelled:
                self.call_from_thread(self._dlc_ready, rows)
        finally:
            set_refresh(False)
            if not worker.is_cancelled:
                self.call_from_thread(self._dlc_finished)

    def _dlc_failed(self, msg: str) -> None:
        self.dlc_error = msg
        self.notify(msg, severity="warning")
        if not self.dlc_loaded:
            self.query_one("#empty", Static).update(Text(msg + " · " + t("tu_cached")))

    def _dlc_finished(self) -> None:
        self._dlc_loading = False
        self._header()

    def _dlc_ready(self, rows: list) -> None:
        self.recs["dlc"], self.dlc_loaded = list(rows), True
        if self.data is not None:
            self.data.dlc, self.data.dlc_at = list(rows), time.time()
            self.save_results()
        self.refill()

    @work(thread=True, exclusive=True, group="snapshot")
    def save_results(self) -> None:
        if self.data is not None:
            try:
                save_snapshot(self.data)
            except (OSError, ValueError, sqlite3.Error) as e:
                if not get_current_worker().is_cancelled:
                    self.call_from_thread(self._save_failed, str(e))

    # ---------------------------------------------------------------- header and key line

    def _header(self) -> None:
        line = Text()
        line.append("sift", style=f"bold {ACCENT}")
        line.append("   ")
        for n, tab in enumerate(TABS, 1):
            start = len(line)
            label = t(TAB_LABEL[tab])
            count = self._shown.get(tab)
            if tab == self.tab:
                line.append(f"{label}", style=f"bold {INK} underline")
            else:
                line.append(f"{label}", style=MUTED)
            if count is not None and self.data is not None and (tab != "dlc" or self.dlc_loaded):
                line.append(f" {count}", style=DIM if tab != self.tab else MUTED)
            line.stylize(Style(meta={"@click": f"app.go_tab('{tab}')"}), start, len(line))
            line.append(" " if self.screen.has_class("narrow") else "   ")
        right = Text()
        if self.tab in WORTH_TABS and self.data is not None:
            mode = t("tu_everything") if self.everything else t("tu_worth", n=num(self._all.get(self.tab, 0)))
            if self.screen.has_class("narrow"):
                mode = mode.split(" · ")[-1]
            right.append(mode + "  ", style=Style(color=MUTED, meta={"@click": "app.everything"}))
        chips = self.view.chips()
        if self.view.macros:
            right.append(" ".join(self.view.macros) + "  ", style=f"bold {VERDICT['meh']}")
        if chips:
            right.append(" · ".join(chips) + "  ", style=VERDICT["meh"])
        if self.query_text:
            right.append(f"“{self.query_text}”  ", style=INK)
        right.append(t("tu_sorted", by=t(f"ui_sort_{self.sort}")), style=MUTED)
        right.stylize(Style(meta={"@click": "app.sort(1)"}))
        stamp = len(right)
        if (self.dlc_error if self.tab == "dlc" else self.refresh_error) and self.data is not None:
            right.append("  " + t("tu_cached"), style=VERDICT["meh"])
        elif self.loading or (self.tab == "dlc" and self._dlc_loading):
            right.append("  " + t("ui_updating"), style=f"{DIM} italic")
        elif self.data and self.data.saved_at:
            updated_at = self.data.dlc_at if self.tab == "dlc" and self.data.dlc_at else self.data.saved_at
            right.append("  " + t("tu_updated", at=time.strftime("%H:%M", time.localtime(updated_at))),
                         style=MUTED)
        right.stylize(Style(meta={"@click": "app.refresh"}), stamp, len(right))
        width = max(40, self.size.width - 4)
        gap = width - len(line.plain) - len(right.plain)
        if gap < 2:
            right.truncate(max(0, width - len(line.plain) - 2), overflow="ellipsis")
            gap = 2
        line.append(" " * gap)
        line.append_text(right)
        self.query_one("#header", Static).update(line)

    def _keys(self) -> None:
        line = Text()
        keys = [("enter", "tu_k_open"), ("/", "tu_k_search"), ("f", "tu_k_filters"),
                ("s", "tu_k_sort"), ("r", "tu_k_refresh"), ("x", "tu_k_hide"),
                ("?", "tu_k_keys"), ("q", "tu_k_quit")]
        if self.screen.has_class("narrow"):
            keys = [("d", "tu_k_details"), *[k for k in keys if k[0] not in ("x", "s")]]
        for key, label in keys:
            start = len(line)
            line.append(key, style=f"bold {INK}")
            line.append(f" {t(label)}", style=MUTED)
            action = {"enter": "open", "/": "search", "f": "filters", "s": "sort(1)", "r": "refresh",
                      "x": "hide('taste')", "?": "help", "q": "quit", "d": "details"}[key]
            line.stylize(Style(meta={"@click": f"app.{action}"}), start, len(line))
            line.append(" " if self.screen.has_class("narrow") else "   ")
        sale = self._sale_note()
        if sale:
            gap = max(2, self.size.width - 4 - len(line.plain) - len(sale))
            line.append(" " * gap)
            line.append(sale, style=MUTED)
        self.query_one("#keys", Static).update(line)

    def _sale_note(self) -> str:
        d = self.data.digest if self.data else None
        if not d:
            return ""
        from ..notify.cards import sale_name
        if d.sale_now:
            return t("tu_sale_now", name=sale_name(d.sale_now.name))
        if d.sale_next:
            import datetime as dt
            days = (d.sale_next.start - dt.date.today()).days
            return t("tu_sale_next", name=sale_name(d.sale_next.name), n=days)
        return ""

    def on_resize(self) -> None:
        self._layout()
        self._header()
        self._keys()

    NARROW, MEDIUM = 100, 135

    def _layout(self) -> None:
        """Narrow terminals keep the list readable: the details pane shrinks, then hides behind `d`."""
        w = self.size.width
        self.screen.set_class(w < self.NARROW, "narrow")
        self.screen.set_class(self.NARROW <= w < self.MEDIUM, "medium")
        self._columns()

    def _wanted_columns(self) -> tuple[str, ...]:
        """The reason shows in the table when the details pane is hidden or the window is wide enough for both;
        in narrow windows it takes the reviews column's place."""
        narrow, medium = self.screen.has_class("narrow"), self.screen.has_class("medium")
        details = not narrow or self.screen.has_class("details-on")
        cols = ["verdict", "price", "cut", "game"]
        if not (details and (medium or narrow)):
            cols.append("why")
        if not narrow:
            cols.append("reviews")
        return tuple(cols)

    def _columns(self) -> None:
        cols = self._wanted_columns()
        if cols == getattr(self, "_cols", ()):
            return
        self._cols = cols
        heads = {"verdict": ("", 9, "left"), "price": (t("col_price"), 9, "right"), "cut": ("%", 5, "right"),
                 "why": (t("tu_col_why"), 22, "left"), "reviews": (t("tu_col_reviews"), 6, "right")}
        for tab in TABS:
            table = self.query_one(f"#t-{tab}", DataTable)
            table.clear(columns=True)
            for key in cols:
                if key == "game":
                    table.add_column(t("col_game") if tab != "dlc" else t("col_dlc"), key="game")
                else:
                    label, width, justify = heads[key]
                    table.add_column(Text(label, justify=justify), key=key, width=width)
        if self.data is not None:
            self.refill()

    def action_details(self) -> None:
        if self._typing():
            return
        self.screen.toggle_class("details-on")
        self._columns()
        self._keys()

    # ---------------------------------------------------------------- tables

    def _visible(self, rows: list) -> list:
        q = self.query_text.lower()
        hidden = self._hidden_cache
        out = [r for r in rows if r.item.appid not in hidden and (not q or q in r.item.name.lower())]
        return self.view.apply(out)

    def refill(self) -> None:
        self._hidden_cache = set(prefs.load_hidden())
        for tab in TABS:
            table = self.query_one(f"#t-{tab}", DataTable)
            keep = self._row_key(table)
            table.clear()
            visible = self._visible(self.recs[tab])
            self._all[tab] = len(visible)
            if tab in WORTH_TABS and not self.everything:
                visible = [r for r in visible if worth_it(r)]
            self._shown[tab] = len(visible)
            wish = set(self.data.ctx.lib.wishlist_ids) if self.data else set()
            for r in visible:
                i = r.item
                v = verdict_of(r)
                name = Text(short_name(i.name, 60), style=INK, overflow="ellipsis", no_wrap=True)
                if tab != "wish" and i.appid in wish:
                    name.append("  ♥", style=VERDICT["wish"])
                if getattr(r, "extras", {}).get("family"):
                    name.append("  ⌂", style=f"bold {VERDICT['family']}")
                if getattr(r, "extras", {}).get("target", {}).get("hit"):
                    name.append("  ◎", style=ACCENT)
                cells = {
                    "verdict": verdict_cell(v),
                    "price": Text(i.final_fmt, style=INK, justify="right"),
                    "cut": Text(f"−{i.cut}%" if i.cut else "", style=MUTED, justify="right"),
                    "game": name,
                    "why": Text(t(f"vs_{v.reason}", n=v.value) if v.reason else "", style=MUTED,
                                overflow="ellipsis", no_wrap=True),
                    "reviews": Text(f"{i.review_pct}%" if i.review_count else "—", style=MUTED, justify="right"),
                }
                table.add_row(*(cells[c] for c in self._cols), key=str(i.appid))
            if keep:
                try:
                    table.move_cursor(row=table.get_row_index(keep))
                except Exception:  # noqa: BLE001 - row gone (hidden / filtered): stay at the top
                    pass
        self._show_current()
        self._header()
        self._keys()

    def _show_current(self) -> None:
        tab = self.tab
        row = self._row_at(tab)
        status = ""
        if row and self.data and tab != "dlc":
            k, p = engine.status_of(self.data.ctx, row.item.appid)
            status = t(k, **p) if k and k != "st_wishlist" else ""
        self.query_one(f"#d-{tab}", Details).show(row, status)
        empty = self.query_one("#empty", Static)
        nothing = self.data is not None and not self._shown.get(tab) and (tab != "dlc" or self.dlc_loaded)
        if nothing:
            msg = t("tu_empty_filtered") if (not self.view.is_default() or self.query_text) else t("tu_empty")
            if tab in WORTH_TABS and not self.everything and self._all.get(tab):
                msg = t("tu_empty_worth", n=num(self._all[tab]))
            empty.update(Text(msg))
        if tab == "dlc" and not self.dlc_loaded and self.data is not None:
            empty.update(Text(self.dlc_error or t("sp_dlc")))
            nothing = True
        empty.set_class(nothing, "show")
        self.query_one("#views").display = not nothing and self.data is not None

    def _row_key(self, table: DataTable) -> str | None:
        if not table.row_count:
            return None
        try:
            return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:  # noqa: BLE001
            return None

    def _row_at(self, tab: str):
        key = self._row_key(self.query_one(f"#t-{tab}", DataTable))
        return next((r for r in self.recs[tab] if str(r.item.appid) == key), None) if key else None

    def _table(self) -> DataTable:
        return self.query_one(f"#t-{self.tab}", DataTable)

    @on(DataTable.RowHighlighted)
    def highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == f"t-{self.tab}":
            self._show_current()

    @on(DataTable.RowSelected)
    def selected(self) -> None:
        self.action_open()

    @on(DataTable.HeaderSelected)
    def sort_column(self, event: DataTable.HeaderSelected) -> None:
        sort = {"verdict": "deal", "price": "price", "cut": "cut", "reviews": "rating"}.get(event.column_key.value)
        if sort:
            self.view.sort = sort
            self.refill()

    def _focus_table(self) -> None:
        self._table().focus()

    def _typing(self) -> bool:
        return isinstance(self.focused, Input)

    # ---------------------------------------------------------------- navigation

    def action_cursor(self, d: int) -> None:
        if self.data is None or self._typing():
            return
        tb = self._table()
        if tb.row_count:
            tb.action_cursor_down() if d > 0 else tb.action_cursor_up()

    def action_cursor_end(self, last: int) -> None:
        if self.data is None or self._typing():
            return
        tb = self._table()
        if tb.row_count:
            tb.move_cursor(row=tb.row_count - 1 if last else 0)

    def action_tab(self, tab: str) -> None:
        if self.data is None or self._typing():
            return                     # nothing to show yet (and never react to stray input during startup)
        self.tab = tab
        self.query_one("#views", ContentSwitcher).current = tab
        if tab == "dlc":
            self._request_dlc()
        self._show_current()
        self._header()
        self.call_after_refresh(self._focus_table)

    def action_go_tab(self, tab: str) -> None:
        self._focus_table()
        self.action_tab(tab)

    def action_step_tab(self, d: int) -> None:
        if self.data is None or self._typing():
            return
        self.action_tab(TABS[(TABS.index(self.tab) + d) % len(TABS)])

    def on_key(self, event: events.Key) -> None:
        if isinstance(self.focused, Input) and self.focused.id == "search" and event.key in ("down", "enter"):
            event.stop()
            event.prevent_default()
            self._focus_table()

    # ---------------------------------------------------------------- the game under the cursor

    def _current(self):
        return self._row_at(self.tab)

    def action_open(self) -> None:
        row = self._current()
        if row:
            webbrowser.open(f"https://store.steampowered.com/app/{row.item.appid}/")
            prefs.log_feedback(row.item.appid, "open")
            self.notify(t("opened", name=row.item.name), timeout=2)

    def action_itad(self) -> None:
        row = self._current()
        if row:
            webbrowser.open(row.item.itad_url)
            prefs.log_feedback(row.item.appid, "info")
            self.notify(t("opened_itad", name=row.item.name), timeout=2)

    def action_bundle(self) -> None:
        row = self._current()
        if not row:
            return
        third = getattr(row, "extras", {}).get("bundle3p")
        if third and getattr(third, "url", ""):
            webbrowser.open(third.url)
        elif row.item.is_bundle and row.item.bundle_url != row.item.url:
            webbrowser.open(row.item.bundle_url)
        else:
            self.notify(t("tu_no_bundle"), timeout=2)
            return
        prefs.log_feedback(row.item.appid, "open")
        self.notify(t("opened_bundle", name=row.item.name), timeout=2)

    def action_hide(self, reason: str) -> None:
        if self._typing():
            return
        row = self._current()
        if not row:
            return
        prefs.hide(row.item.appid, row.item.name, reason)
        self.undo_stack.append(row.item.appid)
        self.refill()
        key = "tu_hidden_taste" if reason == "taste" else "tu_hidden_owned"
        self.notify(t(key, name=short_name(row.item.name, 40)), timeout=5)

    def action_undo(self) -> None:
        if self._typing() or not self.undo_stack:
            return
        appid = self.undo_stack.pop()
        name = prefs.load_hidden().get(appid, {}).get("name", appid)
        prefs.unhide(appid)
        self.refill()
        self.notify(t("restored", name=name), timeout=3)

    # ---------------------------------------------------------------- the list

    def action_search(self) -> None:
        if self.data is None:
            return
        box = self.query_one("#search", Input)
        box.disabled = False
        box.add_class("show")
        box.focus()

    def action_escape(self) -> None:
        box = self.query_one("#search", Input)
        if box.has_class("show"):
            box.value = ""
            box.remove_class("show")
            box.disabled = True
            self.query_text = ""
            self.refill()
            self._focus_table()

    @on(Input.Changed, "#search")
    def search_changed(self, event: Input.Changed) -> None:
        self.query_text = event.value
        self.refill()

    def set_view(self, q: qry.Query) -> None:
        self.view = q
        self.refill()

    def apply_macro(self, name: str) -> None:
        flags = qry.all_macros().get(name, ("", False))[0]
        try:
            q = qry.parse(flags)
        except qry.QueryError as e:
            self.notify(str(e), severity="error", timeout=6)
            return
        q.macros = [name]
        q.sort = q.sort if flags and "--sort" in flags else self.view.sort
        self.set_view(q)
        if q.tab in TABS and q.tab != self.tab:
            self.action_tab(q.tab)

    def save_macro(self, name: str, q: qry.Query) -> None:
        import argparse

        from ..cli import build_parser
        parser = build_parser()
        commands = set(next(a.choices for a in parser._actions if isinstance(a, argparse._SubParsersAction)))
        try:
            qry.save_macro(name, replace(q, tab=self.tab).to_args(), commands | {"help", "macros"})
        except qry.QueryError as e:
            self.notify(str(e), severity="error", timeout=6)
            return
        self.view.macros = [name.lower()]
        self._header()
        self.notify(t("m_saved", name=name.lower()), timeout=4)

    def action_filters(self) -> None:
        if self.data is None:
            return
        self.push_screen(FilterPanel(self), lambda _: self._focus_table())

    def action_help(self) -> None:
        self.push_screen(HelpScreen(), lambda _: self._focus_table())

    def action_reset(self) -> None:
        if self._typing() or self.data is None:
            return
        self.set_view(qry.Query(tab=self.view.tab, sort=self.view.sort))
        self.notify(t("ui_cleared"), timeout=2)

    def action_everything(self) -> None:
        if self._typing() or self.data is None:
            return
        self.everything = not self.everything
        self.refill()

    def action_sort(self, d: int) -> None:
        if self._typing() or self.data is None:
            return
        cur = self.sort if self.sort in SORTS else "deal"
        self.view.sort = SORTS[(SORTS.index(cur) + d) % len(SORTS)]
        self.refill()

    def action_refresh(self) -> None:
        if self._typing() or self.loading or self._dlc_loading:
            return
        if self.tab == "dlc" and self.data is not None:
            self._request_dlc(force=True)
            return
        from ..db import set_refresh
        set_refresh(True)
        self.fresh = False
        self.loading = True
        self.refresh_error = ""
        self._header()
        self.load(refresh=True)


def run_app(query: qry.Query | None = None) -> None:
    # The probe must happen before Textual owns stdin, otherwise the terminal's reply arrives as keystrokes
    # (it once landed in the search box and emptied the list).
    SiftApp(images=probe_covers(config.cfg.settings.covers), query=query).run()


__all__ = ["SiftApp", "Loader", "Data", "FilterPanel", "HiddenPanel", "HelpScreen", "run_app", "render_details"]
