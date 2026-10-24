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
            assert app.tab == "discover"
            await pilot.press("left", "left")
            assert app.tab == "picks"
    run(go())


def test_verdict_column_and_details_explain_the_price(data):
    async def go():
        app = SiftApp(StubLoader(data), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            t = app.query_one("#t-picks")
            by_name = {t.get_row_at(i)[NAME].plain: t.get_row_at(i)[0].plain for i in range(t.row_count)}
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


def test_instant_cached_paint_then_fresh_and_lazy_dlc(data):
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
            await pilot.press("4")
            for _ in range(50):
                await pilot.pause(0.02)
                if "dlc" in loader.calls:
                    break
            assert "dlc" in loader.calls
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


def test_discover_tab_is_one_plain_list(world):
    async def go():
        app = SiftApp(StubLoader(world), images=False)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            await pilot.press("3")
            assert app.tab == "discover"
            assert set(rows(app, "discover")) == {"Tiny Puzzle", "Another Puzzle", "Space Tactics"}
            assert len(app.query_one("#t-discover").columns) == 5        # verdict · price · cut · game · reviews
            await pilot.pause()
            info = str(app.query_one("#d-discover").query_one("#info").render())
            assert rows(app, "discover")[0] in info and "new for you" in info
    run(go())


def test_cli_query_opens_the_right_tab_with_filters(world):
    async def go():
        q = query.Query(tab="discover", max_price=3)
        app = SiftApp(StubLoader(world), images=False, query=q)
        async with app.run_test(size=(150, 40)) as pilot:
            await ready(pilot, app)
            assert app.tab == "discover"
            assert rows(app, "discover") == ["Tiny Puzzle"]                  # $1.99 ≤ 3; the others cost more
            assert "≤" in header(app)
            await pilot.press("0")                                          # reset
            await pilot.pause()
            assert len(rows(app, "discover")) == 3
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
            assert app.tab == "discover" and app.view.macros == ["gems"] and app.view.min_rating == 93
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
