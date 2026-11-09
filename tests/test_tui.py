"""G9: the full-screen app works headless and fully from the keyboard: tabs, details, search, sort,
the filter panel (switches, limits, saved filters, hidden games), hide + undo, open, covers."""
import asyncio

import pytest

from helpers import HORROR, PUZZLE, RACING, item, make_ctx, offline_digest, racing_fan
from steamsift import engine, prefs
from steamsift import discover as disc, query
from steamsift.itad import History
from steamsift.tui.app import Data, FilterPanel, HelpScreen, HiddenPanel, SiftApp, render_details


class StubLoader:
    def __init__(self, data, delay: float = 0.0, dlc=None):
        self.data, self.delay, self.dlc, self.calls = data, delay, dlc or [], []

    def load(self, progress=lambda key: None, stale: bool = False):
        import time
        self.calls.append("stale" if stale else "fresh")
        progress("sp_library")
        time.sleep(self.delay)
        return self.data

    def load_dlc(self):
        self.calls.append("dlc")
        return self.dlc


@pytest.fixture
def data(monkeypatch):
    lib, meta = racing_fan()
    lib.wishlist = [{"appid": 50, "priority": 0, "date_added": 0}]
    wish = {50: item(50, "Wished puzzle", PUZZLE, cut=60)}
    cands = {60: item(60, "Rally Kings", RACING, cut=80, price=499), 61: item(61, "Night Drive", RACING, cut=50,
                                                                            price=1299),
             62: item(62, "Fear House", HORROR, cut=90, price=199)}
    offline_digest(monkeypatch, history={60: 80, 61: 75, 62: 95})
    ctx = make_ctx(lib, meta, wish, cands)
    d = engine.build_digest(ctx, limit=20, min_discount=0)
    yield Data(ctx, d, [])
    prefs.clear_hidden()


@pytest.fixture(autouse=True)
def every_row(monkeypatch):
    """Most tests here are about other features: show every verdict, not only the worth-it list."""
    monkeypatch.setattr(SiftApp, "WORTH_IT_FIRST", False)


async def ready(pilot, app):
    for _ in range(100):
        await pilot.pause(0.02)
        if app.data is not None:
            return
    raise AssertionError("app never finished loading")


NAME = 3     # verdict · price · cut · game · reviews


def rows(app, tab="picks"):
    t = app.query_one(f"#t-{tab}")
    return [t.get_row_at(i)[NAME].plain.split("  ")[0] for i in range(t.row_count)]


def header(app) -> str:
    return str(app.query_one("#header").render())


TACTICS = {"Turn-Based Tactics": 1000, "Strategy": 800, "Sci-fi": 600, "Tactical": 500, "Atmospheric": 300}


@pytest.fixture
def world(monkeypatch):
    """Picks + a discover pool with two puzzle games (a lane) and one tactics game (more to explore)."""
    disc._seen._data, disc._seen._dirty = {}, set()
    lib, meta = racing_fan()
    cands = {60: item(60, "Rally Kings", RACING, cut=80, price=499),
             70: item(70, "Tiny Puzzle", PUZZLE, cut=70, price=199, review_pct=97, review_count=3000),
             73: item(73, "Another Puzzle", PUZZLE, cut=60, price=399, review_pct=95, review_count=900),
             71: item(71, "Space Tactics", TACTICS, cut=75, price=999, review_pct=94, review_count=20000)}
    offline_digest(monkeypatch, history={60: 80, 70: 70, 73: 75, 71: 80})
    ctx = make_ctx(lib, meta, {}, cands)
    yield Data(ctx, engine.build_digest(ctx, limit=20, min_discount=0, discover=True), [])
    prefs.clear_hidden()


def run(coro):
    asyncio.run(coro)


def test_loads_tabs_and_details(data):
    async def go():
        app = SiftApp(StubLoader(data), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            assert set(rows(app)) == {"Rally Kings", "Night Drive", "Fear House"}
            info = str(app.query_one("#d-picks").query_one("#info").render())
            assert rows(app)[0] in info
            assert "Deals" in header(app) and "Wishlist" in header(app)
            await pilot.press("2")
            assert app.tab == "wish" and rows(app, "wish") == ["Wished puzzle"]
            await pilot.press("right")
            assert app.tab == "picks"                                      # two tabs: Deals and Wishlist
            await pilot.press("left")
            assert app.tab == "wish"
            assert "Discover" not in header(app) and "DLC" not in header(app)
    run(go())


def test_verdict_column_and_details_explain_the_price(data):
    async def go():
        app = SiftApp(StubLoader(data), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            t = app.query_one("#t-picks")
            by_name, word = {}, ""          # the word is written where a run of one verdict starts
            for i in range(t.row_count):
                word = t.get_row_at(i)[0].plain.strip("▎ ") or word
                by_name[t.get_row_at(i)[NAME].plain] = word
            assert by_name["Rally Kings"] == "OK"                       # its record, but no log to say it is rare
            assert by_name["Night Drive"] == "NOPE"                     # −50% when it has been −75%: half the price
    run(go())
    rec = next(r for r in data.digest.picks if r.item.name == "Night Drive")
    text = render_details(rec).plain
    assert "NOPE" in text and "it has been 50% cheaper" in text


def test_sale_bars_and_facts_from_the_real_log():
    from steamsift.recommender import Rec
    h = History(best_cut=80, low_2y_cut=80, sales_2y=19, gap_days=43, typical_cut=75, covered_days=900,
                points=[("2025-11-01", 80), ("2025-11-10", 0), ("2026-06-25", 75), ("2026-07-09", 0)])
    rec = Rec(item(1, "Resident Evil 2", HORROR, cut=80), 0.5, 0.8, 0.0, "", False, hist=h)
    rec.rescore()
    out = render_details(rec, width=50).plain
    assert "GREAT" in out and "19 sales in 2 years" in out and "usually −75%" in out
    assert any(ch in out for ch in "▁▂▃▄▅▆▇█")


def test_sale_bars_label_each_sale_and_show_the_depth():
    import datetime as dt
    from steamsift.tui.app import BAR_ROWS, sale_bars
    day = lambda ago: (dt.date.today() - dt.timedelta(days=ago)).isoformat()
    h = History(best_cut=90, points=[(day(600), 75), (day(590), 0), (day(300), 90), (day(290), 0)])
    lines = sale_bars(h, 40, "green").plain.split("\n")
    assert len(lines) == 1 + BAR_ROWS
    assert "−75%" in lines[0] and "−90%" in lines[0]                 # how much, right above each sale
    top = lines[1]
    record = lines[0].index("−90%")
    assert top[record:record + 4].strip() and not top[:10].strip()   # only the record reaches the top line


def test_hide_and_undo_and_hidden_panel(data):
    async def go():
        app = SiftApp(StubLoader(data), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            first = rows(app)[0]
            await pilot.press("x")                                   # not for me
            await pilot.pause()
            assert first not in rows(app)
            assert any(h["name"] == first and h["reason"] == "taste" for h in prefs.load_hidden().values())
            await pilot.press("u")
            await pilot.pause()
            assert first in rows(app) and not prefs.load_hidden()
            await pilot.press("X")                                   # I own it elsewhere
            await pilot.pause()
            assert any(h["reason"] == "owned" for h in prefs.load_hidden().values())
            await pilot.press("f", "h")
            assert isinstance(app.screen, HiddenPanel)
            await pilot.press("enter")                               # bring it back
            await pilot.pause()
            assert not prefs.load_hidden()
            await pilot.press("escape", "escape")
            await pilot.pause()
            assert first in rows(app)
    run(go())


def test_search_sort_and_filter_panel_apply_live(data):
    async def go():
        app = SiftApp(StubLoader(data), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            await pilot.press("slash")
            await pilot.press(*"night")
            await pilot.pause()
            assert rows(app) == ["Night Drive"]
            await pilot.press("escape")
            await pilot.pause()
            assert len(rows(app)) == 3
            await pilot.press("s")                                   # deal → cut
            await pilot.pause()
            assert app.sort == "cut" and rows(app)[0] == "Fear House"
            await pilot.press("S")
            assert app.sort == "deal"
            await pilot.press("f")
            assert isinstance(app.screen, FilterPanel)
            await pilot.press("l")                                   # record lows, applied behind the panel
            await pilot.pause()
            assert rows(app) == ["Rally Kings"]     # only true record lows: −90% vs −95% and −50% vs −75% drop out
            await pilot.press("l")
            await pilot.pause()
            assert len(rows(app)) == 3
            await pilot.press("p")                                   # price up to …
            await pilot.press(*"3", "enter")
            await pilot.pause()
            assert rows(app) == ["Fear House"]
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, FilterPanel)
            await pilot.press("0")                                   # reset
            await pilot.pause()
            assert len(rows(app)) == 3
    run(go())


def test_open_logs_interest(data, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)

    async def go():
        app = SiftApp(StubLoader(data), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            await pilot.press("enter")
            await pilot.pause()
    run(go())
    assert opened and opened[0].startswith("https://store.steampowered.com/app/")
    appid = int(opened[0].rstrip("/").rsplit("/", 1)[1])
    assert prefs.interest().get(appid, 0) >= 2


def test_loader_errors_are_shown_not_crashing(data):
    class Broken:
        def load(self, progress=lambda key: None, stale: bool = False):
            raise RuntimeError("Steam is down")

        def load_dlc(self):
            return []

    async def go():
        app = SiftApp(Broken(), images=False)
        async with app.run_test(size=(120, 30)) as pilot:
            for _ in range(50):
                await pilot.pause(0.02)
            assert "Steam is down" in str(app.query_one("#loading-text").render())
    run(go())


def test_stray_terminal_replies_never_become_search_text(data):
    """Regression: Windows Terminal's reply to the image probe (`ESC[6;20;10t`) was typed into the search box."""
    async def go():
        app = SiftApp(StubLoader(data, delay=0.4), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.press(*"[6;20;10t")                       # arrives while the app is still loading
            await ready(pilot, app)
            assert app.query_text == "" and app.query_one("#search").disabled
            assert len(rows(app)) == 3 and app.tab == "picks"
    run(go())


def test_instant_cached_paint_then_fresh_and_lazy_dlc(data, monkeypatch):
    from steamsift import config
    monkeypatch.setattr(config.cfg.settings, "dlc_tab", True)
    loader = StubLoader(data, dlc=[])

    async def go():
        app = SiftApp(loader, images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            for _ in range(50):
                await pilot.pause(0.02)
                if app.fresh:
                    break
            assert app.fresh and loader.calls[:2] == ["stale", "fresh"]
            assert "dlc" not in loader.calls, "DLC is fetched only when its tab is opened"
            await pilot.press("3")
            for _ in range(50):
                await pilot.pause(0.02)
                if "dlc" in loader.calls:
                    break
            assert "dlc" in loader.calls
    run(go())


def test_recent_results_open_without_starting_another_scan(data):
    import time
    data.saved_at = time.time()
    loader = StubLoader(data)

    async def go():
        app = SiftApp(loader, images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            await app.workers.wait_for_complete()
            assert len(rows(app)) == 3
            assert loader.calls == ["stale"]
            assert app.fresh
    run(go())


def test_repeated_refresh_is_one_scan_and_keeps_selected_game(data):
    from steamsift import db
    loader = StubLoader(data, delay=0.15)

    async def go():
        app = SiftApp(loader, images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            await app.workers.wait_for_complete()
            await pilot.press("down")
            selected = app._current().item.appid
            before = len(loader.calls)
            app.action_refresh()
            app.action_refresh()
            assert app._current().item.appid == selected
            await app.workers.wait_for_complete()
            assert len(loader.calls) == before + 1
            assert app._current().item.appid == selected
            assert not db._REFRESH
    run(go())


def test_failed_refresh_keeps_previous_rows_and_reports_stale(data):
    class Offline(StubLoader):
        def load(self, progress=lambda key: None, stale=False):
            if not stale:
                raise RuntimeError("Steam is down")
            return self.data

    async def go():
        app = SiftApp(Offline(data), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            await app.workers.wait_for_complete()
            assert len(rows(app)) == 3
            assert not app.fresh
            assert "cached" in header(app).lower()
    run(go())


def test_mouse_navigation_and_controls(data, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)

    async def go():
        app = SiftApp(StubLoader(data), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            await app.workers.wait_for_complete()
            # Click the actual Wishlist text, without relying on a new widget type.
            label = header(app).index("Wishlist")
            await pilot.click("#header", offset=(label + 2, 0))
            assert app.tab == "wish"
            assert rows(app, "wish") == ["Wished puzzle"]
            await pilot.click("#t-wish", offset=(35, 1))
            assert not opened, "a single click selects a game rather than opening a browser"
            await pilot.press("enter")
            assert opened and "/50/" in opened[-1]
            opened.clear()
            await pilot.double_click("#t-wish", offset=(35, 1))
            assert len(opened) == 1
            # The footer is an action bar, not just keyboard instructions.
            keys = str(app.query_one("#keys").render())
            await pilot.click("#keys", offset=(keys.index("filters") + 2, 0))
            assert isinstance(app.screen, FilterPanel)
            await pilot.pause()
            await pilot.click("#opts", offset=(5, 1))
            await pilot.pause()
            assert app.view.buy
            await pilot.click("#opts", offset=(5, 1))
            await pilot.pause()
            assert not app.view.buy
            title = str(app.screen.query_one(".head").render())
            await pilot.click(".head", offset=(title.index("×"), 0))
            assert not isinstance(app.screen, FilterPanel)
            await pilot.click("#header", offset=(label + 2, 0))
            assert app.tab == "wish"
    run(go())


def test_saved_dlc_revalidates_once_when_opened_and_refreshes_without_main_scan(data, monkeypatch):
    from steamsift import config
    from steamsift.engine import DlcRow
    monkeypatch.setattr(config.cfg.settings, "dlc_tab", True)
    old = DlcRow(item(80, "Old DLC"), "you", "you", 5, "Base", 0.5, 0.8)
    new = DlcRow(item(81, "Fresh DLC"), "you", "you", 5, "Base", 0.5, 0.8)
    data.dlc, data.dlc_at = [old], 1
    loader = StubLoader(data, dlc=[new])

    async def go():
        app = SiftApp(loader, images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            await app.workers.wait_for_complete()
            await pilot.press("3")
            await app.workers.wait_for_complete()
            assert rows(app, "dlc") == ["Fresh DLC"]
            scans = loader.calls.count("fresh")
            app.action_refresh()
            app.action_refresh()
            await app.workers.wait_for_complete()
            assert loader.calls.count("fresh") == scans
            assert loader.calls.count("dlc") == 2
    run(go())


def test_first_results_are_usable_while_history_is_still_loading(data):
    import threading
    gate = threading.Event()

    class Staged(StubLoader):
        def load(self, progress=lambda key: None, stale=False):
            if stale:
                raise LookupError("first run")
            progress(data)
            assert gate.wait(3), "history should not block the first usable results"
            return data

    async def go():
        app = SiftApp(Staged(data), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            try:
                await ready(pilot, app)
                assert len(rows(app)) == 3 and app.loading
                await pilot.press("2")
                assert app.tab == "wish"
            finally:
                gate.set()
            await app.workers.wait_for_complete()
            assert app.fresh
    run(go())


def test_periodic_refresh_recovers_after_a_transient_failure(data):
    import time
    data.saved_at = time.time()
    data.complete = False
    class Flaky(StubLoader):
        failed = False

        def load(self, progress=lambda key: None, stale=False):
            if not stale and not self.failed:
                self.failed = True
                raise RuntimeError("temporarily offline")
            return data

    async def go():
        app = SiftApp(Flaky(data), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            await app.workers.wait_for_complete()
            assert not app.fresh
            app._retry_at = 0
            app._refresh_if_due()
            await app.workers.wait_for_complete()
            assert app.fresh and len(rows(app)) == 3
    run(go())


def test_checkpoint_failure_does_not_close_the_app(data, monkeypatch):
    import sqlite3
    from steamsift import db

    def fail():
        raise sqlite3.OperationalError("disk full")

    async def go():
        app = SiftApp(StubLoader(data), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            await app.workers.wait_for_complete()
            monkeypatch.setattr(db.db(), "flush", fail)
            app.checkpoint()
            await app.workers.wait_for_complete()
            await pilot.press("2")
            assert app.tab == "wish" and rows(app, "wish") == ["Wished puzzle"]
    run(go())


def test_half_block_cover_keeps_aspect_and_colours():
    from PIL import Image
    from steamsift.tui.cover import half_block_rows
    img = Image.new("RGB", (460, 215), (255, 0, 0))
    img.paste((0, 0, 255), (0, 108, 460, 215))                     # bottom half blue
    rows = half_block_rows(img, 40, 12)
    assert len(rows[0]) == 40 and 8 <= len(rows) <= 12             # 460x215 header ≈ 40 x 9 cells
    top, bottom = rows[0][0].style, rows[-1][0].style
    assert top.color.triplet == (255, 0, 0) and bottom.bgcolor.triplet == (0, 0, 255)
    tall = half_block_rows(Image.new("RGB", (100, 1000)), 40, 12)
    assert len(tall) == 12 and len(tall[0]) < 40                   # fit by height when too tall


def test_app_renders_real_cover_widget(data, monkeypatch):
    """The default 'blocks' cover renders inside the running app (no terminal queries involved)."""
    from PIL import Image
    from steamsift.tui import app as app_mod
    from steamsift.tui.cover import HalfBlockCover
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setattr(app_mod.Details, "fetch_cover", lambda self, appid, url: self._set_cover(
        Image.new("RGB", (460, 215), (10, 120, 200))))

    async def go():
        app = SiftApp(StubLoader(data), images="blocks")
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            await pilot.pause(0.2)
            cover = app.query_one("#d-picks").query_one("#cover")
            assert isinstance(cover, HalfBlockCover) and cover.image is not None
            line = cover.render_line(0)
            assert line.text.startswith("▀") and cover.size.width > 20
            await pilot.press("j", "down", "down")                  # moving through rows keeps working
            await pilot.pause(0.2)
    run(go())


def test_sixel_cover_emits_real_pixels(data, monkeypatch):
    """`covers = auto` on Windows Terminal / foot / WezTerm → a Sixel picture, not half blocks."""
    from PIL import Image
    from textual_image.widget import SixelImage
    from steamsift.tui import app as app_mod
    monkeypatch.setattr(app_mod.Details, "fetch_cover", lambda self, appid, url: self._set_cover(
        Image.new("RGB", (460, 215), (200, 40, 40))))

    async def go():
        app = SiftApp(StubLoader(data), images="sixel")
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            await pilot.pause(0.3)
            details = app.query_one("#d-picks")
            cover = details.query_one("#cover")
            assert isinstance(cover, SixelImage) and details.has_class("pixels")
            impl = cover.children[0]
            strips = impl.render_lines(impl.region.reset_offset)
            payload = "".join(seg.text for strip in strips for seg in strip)
            assert "\x1bP" in payload and impl.region.height >= 6       # DCS sixel data, sized by aspect ratio
            await pilot.press("down", "down")                            # switching games swaps the picture
            await pilot.pause(0.2)
    run(go())


def test_cover_mode_resolution(monkeypatch):
    from steamsift.tui import app as app_mod
    monkeypatch.setattr(app_mod, "_probed", None)
    assert app_mod.cover_mode("auto") == "blocks"                 # not probed (pipes, tests) → safe default
    monkeypatch.setattr(app_mod, "_probed", "sixel")
    assert app_mod.cover_mode("auto") == "sixel"
    assert app_mod.cover_mode("blocks") == "blocks" and app_mod.cover_mode(False) == "off"


def test_dlc_tab_is_hidden_until_switched_on_in_the_filter_panel(data, monkeypatch):
    from steamsift import config
    monkeypatch.setattr(config.cfg.settings, "dlc_tab", False)
    monkeypatch.setattr(config.Settings, "save", lambda self: None)

    async def go():
        app = SiftApp(StubLoader(data), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            await pilot.press("3")
            assert app.tab == "picks" and "DLC" not in header(app)
            await pilot.press("f", "D")
            await pilot.pause()
            assert config.cfg.settings.dlc_tab and "DLC" in header(app)
            await pilot.press("escape", "3")
            assert app.tab == "dlc"
            await pilot.press("f", "D", "escape")
            await pilot.pause()
            assert app.tab == "picks" and "DLC" not in header(app)
    run(go())


def test_cli_query_opens_the_right_tab_with_filters(world):
    async def go():
        q = query.Query(tab="wish", max_price=3)
        app = SiftApp(StubLoader(world), images=False, query=q)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            assert app.tab == "wish"
            await pilot.press("1")
            assert rows(app) == ["Tiny Puzzle"]                              # $1.99 ≤ 3; the others cost more
            assert "≤" in header(app)
            await pilot.press("0")                                          # reset
            await pilot.pause()
            assert len(rows(app)) == 4
    run(go())


def test_filter_panel_saves_and_applies_saved_filters(world):
    async def go():
        app = SiftApp(StubLoader(world), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            await pilot.press("f", "p", "2", "enter")                       # price up to 2
            await pilot.pause()
            assert all("Rally" not in x for x in rows(app))                 # $4.99 > 2
            await pilot.press("s", *"pocket", "enter")                      # save as "pocket"
            await pilot.pause()
            assert query.all_macros()["pocket"] == ("-t -b 2", False)
            await pilot.press("0")                                          # reset all (inside the panel)
            await pilot.pause()
            assert "Rally Kings" in rows(app) and len(rows(app)) == 4
            panel = app.screen
            gems = next(k for k, v in panel._keys.items() if v == "mc:gems")
            await pilot.press(gems)                                         # saved filters apply by number
            await pilot.pause()
            assert app.tab == "picks" and app.view.macros == ["gems"] and app.view.min_rating == 93
            assert "gems" in header(app)
    run(go())
    query.remove_macro("pocket")


def test_keyboard_only_bundle_help_and_navigation(monkeypatch):
    lib, meta = racing_fan()
    b_it = item(60, "Rally Bundle", RACING, cut=80, price=499)
    b_it.bundle_id = 777
    b_it.included_games = 3
    b_it.bundle_discount = 20
    b_it.complete_the_set = True
    cands = {
        60: b_it,
        61: item(61, "Night 2Y Low", RACING, cut=70, price=699),
        62: item(62, "Frequent Cut", HORROR, cut=50, price=999),
    }
    offline_digest(monkeypatch, history={
        60: History(best_cut=80, low_2y_cut=80, covered_days=730, sales_2y=1, gap_days=240),
        61: History(best_cut=85, low_2y_cut=70, covered_days=730, sales_2y=2, gap_days=190),
        62: History(best_cut=90, low_2y_cut=85, covered_days=730, sales_2y=18, gap_days=30),
    })
    ctx = make_ctx(lib, meta, {}, cands)
    d = Data(ctx, engine.build_digest(ctx, limit=20, min_discount=0), [])
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)

    async def go():
        app = SiftApp(StubLoader(d), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            while rows(app)[app.query_one("#t-picks").cursor_row] != "Rally Bundle":
                await pilot.press("j")
            await pilot.press("b")
            await pilot.pause()
            assert opened and "/bundle/777/" in opened[-1]
            await pilot.press("question_mark")
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, HelpScreen)
            await pilot.press("f", "b")                                     # bundles and sets only
            await pilot.pause()
            assert rows(app) == ["Rally Bundle"]
            await pilot.press("b", "y")                                     # off again; lowest in 2 years on
            await pilot.pause()
            assert set(rows(app)) == {"Rally Bundle", "Night 2Y Low"}
            await pilot.press("escape", "0")
            await pilot.pause()
            await pilot.press("]")
            assert app.tab == "wish"
            await pilot.press("[")
            assert app.tab == "picks"
            await pilot.press("G")
            assert app.query_one("#t-picks").cursor_row == len(rows(app)) - 1
            await pilot.press("g")
            assert app.query_one("#t-picks").cursor_row == 0
    run(go())
    prefs.clear_hidden()


def test_narrow_terminal_keeps_names_and_toggles_details(data):
    async def go():
        app = SiftApp(StubLoader(data), images=False)
        async with app.run_test(size=(80, 24)) as pilot:
            await ready(pilot, app)
            assert app.screen.has_class("narrow")
            assert not app.query_one("#d-picks").display or app.query_one("#d-picks").styles.display == "none"
            assert app.query_one("#t-picks").size.width > 60                 # the list gets the whole width
            await pilot.press("d")
            assert app.screen.has_class("details-on")
    run(go())


@pytest.mark.parametrize("width", [80, 100, 150, 180])
def test_long_game_names_keep_the_last_column_visible_at_every_width(data, width):
    data.digest.picks[0].item.name = "A very long game name " * 5

    async def go():
        app = SiftApp(StubLoader(data), images=False)
        async with app.run_test(size=(width, 32)) as pilot:
            await ready(pilot, app)
            await app.workers.wait_for_complete()
            await pilot.pause()
            head = app.query_one("#t-picks").render_line(0).text
            # narrow: the reason replaces reviews · medium: the reason is in the details pane · wide: your tags
            # beside the game, and from 172 columns the reason too
            assert ("why" in head, "rev." in head) == {80: (True, False), 100: (False, True), 150: (False, True),
                                                       180: (True, True)}[width]
            assert ("your tags" in head) == (width >= 150)
            if width == 180:
                t = app.query_one("#t-picks")
                assert "was 50% cheaper" in [t.get_row_at(i)[5].plain for i in range(t.row_count)]
    run(go())


def test_deals_open_on_the_worth_it_list(monkeypatch):
    monkeypatch.setattr(SiftApp, "WORTH_IT_FIRST", True)
    lib, meta = racing_fan()
    cands = {60: item(60, "Rally Kings", RACING, cut=80, price=499),
             61: item(61, "Night Drive", RACING, cut=50, price=1299),
             62: item(62, "Fear House", HORROR, cut=90, price=199)}
    offline_digest(monkeypatch, history={
        60: History(80, sales_2y=19, gap_days=43, covered_days=730),     # GREAT: record, back every 43 days
        61: 75,                                                         # NOPE
        62: 95})                                                        # OK
    ctx = make_ctx(lib, meta, {}, cands)
    data = Data(ctx, engine.build_digest(ctx, limit=20, min_discount=0), [])

    async def go():
        app = SiftApp(StubLoader(data), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            assert rows(app) == ["Rally Kings"]
            assert "Deals 1" in header(app) and "worth it · a: all 3" in header(app)
            await pilot.press("a")
            assert set(rows(app)) == {"Rally Kings", "Night Drive", "Fear House"}
            assert "all deals" in header(app)
            await pilot.press("a")
            prefs.hide(60, "Rally Kings", "taste")
            app.refill()
            assert rows(app) == [] and "a shows all 2 discounts" in str(app.query_one("#empty").render())
    try:
        run(go())
    finally:
        prefs.clear_hidden()


def test_wishlist_shows_games_at_full_price_with_when_to_wait(monkeypatch):
    import datetime as dt
    from steamsift.calendar import Event
    lib, meta = racing_fan()
    lib.wishlist = [{"appid": 52, "priority": 2, "date_added": 0}, {"appid": 50, "priority": 0, "date_added": 0},
                    {"appid": 51, "priority": 1, "date_added": 0}]
    wish = {50: item(50, "Wished puzzle", PUZZLE, cut=60),
            51: item(51, "Full price one", PUZZLE, cut=0, price=2000),
            52: item(52, "Full price two", PUZZLE, cut=0, price=1000)}
    winter = Event("Steam Winter Sale", "sale", dt.date.today() + dt.timedelta(days=19),
                   dt.date.today() + dt.timedelta(days=33))
    offline_digest(monkeypatch, events=[winter], history={
        50: 80, 51: History(75, typical_cut=60, sales_2y=8, gap_days=45, since_last_days=20, covered_days=730)})
    ctx = make_ctx(lib, meta, wish, {})
    d = engine.build_digest(ctx, limit=20, min_discount=0)
    assert [r.item.name for r in d.waiting] == ["Full price one", "Full price two"]      # wishlist order

    async def go():
        app = SiftApp(StubLoader(Data(ctx, d, [])), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            await pilot.press("2")
            assert rows(app, "wish") == ["Wished puzzle", "Full price one", "Full price two"]
            assert "1 on sale · 2 waiting" in header(app)
            t = app.query_one("#t-wish")
            assert t.get_row_at(1)[4].plain == "−60% every ~45 d"
            await pilot.press("j")
            await pilot.pause()
            info = str(app.query_one("#d-wish").query_one("#info").render())
            assert "Not on sale" in info and "usually −60%, about $8.00" in info
            assert "next sale due in ~25 days" in info and "Winter Sale in 19 days" in info
            await pilot.press("f", "c", *"50", "enter", "escape")                         # a filter: discounts only
            await pilot.pause()
            assert rows(app, "wish") == ["Wished puzzle"]
    run(go())


def test_price_alert_from_the_app(data):
    from steamsift.tui.app import parse_price

    assert (parse_price("9.99"), parse_price("$9,99"), parse_price("1 500 ₸"), parse_price("1.299,50")) == \
        (999, 999, 150000, 129950)
    assert parse_price("abc") is None and parse_price("0") is None

    async def go():
        app = SiftApp(StubLoader(data), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            appid = app._current().item.appid
            await pilot.press("t", *"4.5", "enter")
            await pilot.pause()
            assert prefs.targets()[appid]["price_cents"] == 450
            assert "◎ alert at ≤ $4.50" in str(app.query_one("#d-picks").query_one("#info").render())
            await pilot.press("t", "enter")
            await pilot.pause()
            assert prefs.targets()[appid]["price_cents"] is None
            await pilot.press("t", "-", "enter")
            await pilot.pause()
            assert appid not in prefs.targets()
            await pilot.press("t", "escape")
            assert app.focused is app.query_one("#t-picks")
    run(go())


def test_forecast_says_when_to_come_back(data):
    import datetime as dt
    from steamsift.i18n import day_month
    from dataclasses import replace
    from steamsift.recommender import Verdict
    from steamsift.tui.app import why_text, verdict_of
    rec = next(r for r in data.digest.picks if r.item.name == "Night Drive")          # NOPE: it has been cheaper
    day = dt.date.today() + dt.timedelta(days=12)
    rec.extras["next_sale"] = {"day": day, "name": "Steam Winter Sale"}
    assert f"Wait until {day_month(day)} (Winter Sale)." in render_details(rec).plain
    rec.extras["next_sale"] = {"day": day, "name": ""}
    assert f"Wait: its next sale is due around {day_month(day)}." in render_details(rec).plain
    rec.extras["next_sale"] = {"day": dt.date.today(), "name": ""}
    assert "its next sale is due any day now" in render_details(rec).plain
    waiting = replace(rec, item=replace(rec.item, cut=0), hist=History(75, typical_cut=60, gap_days=45),
                      verdict=Verdict(), extras={"next_sale": {"day": day, "name": ""}})
    assert why_text(waiting, verdict_of(waiting)) == f"−60% around {day_month(day)}"


def test_like_key_marks_the_game_and_can_be_taken_back(data):
    async def go():
        app = SiftApp(StubLoader(data), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            first = app._current().item
            await pilot.press("l")
            await pilot.pause()
            assert prefs.likes() == {first.appid}
            t = app.query_one("#t-picks")
            assert any("★" in t.get_row_at(i)[NAME].plain for i in range(t.row_count))
            await pilot.press("l")
            await pilot.pause()
            assert prefs.likes() == set()
    run(go())
