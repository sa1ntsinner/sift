"""G10: sale calendar from Valve's page, wait-for-sale and fest hints, cheaper-elsewhere by region."""
import datetime as dt

import pytest

from conftest import FIXTURES
from helpers import PUZZLE, RACING, item, make_ctx, offline_digest, racing_fan, sale
from steamsift import calendar, config, engine, itad
from steamsift.notify.cards import notes_for

PAGE = (FIXTURES / "upcoming_events.html").read_text(encoding="utf-8")


def test_calendar_parses_seasonal_sales_and_fests():
    evs = calendar.parse(PAGE)
    sales = {e.name: (e.start, e.end) for e in evs if e.kind == "sale"}
    assert sales["Steam Winter Sale"] == (dt.date(2026, 12, 17), dt.date(2027, 1, 4))
    assert sales["Steam Summer Sale"] == (dt.date(2027, 6, 24), dt.date(2027, 7, 8))
    fests = {e.name: e for e in evs if e.kind == "fest"}
    assert len(fests) >= 10
    racing = fests["Racing Fest"]
    assert racing.start == dt.date(2027, 4, 12) and "Racing" in racing.tags
    assert all(e.end >= e.start for e in evs), "fests crossing New Year roll the end year over"


def test_current_next_and_matching_fests():
    evs = calendar.parse(PAGE)
    assert calendar.current_sale(dt.date(2026, 12, 20), evs=evs).name == "Steam Winter Sale"
    assert calendar.next_sale(dt.date(2026, 12, 1), evs=evs).name == "Steam Winter Sale"
    assert calendar.next_sale(dt.date(2026, 10, 9), within_days=45, evs=evs) is None
    mine = calendar.fests_for(["Racing", "Automobile Sim"], dt.date(2027, 3, 1), evs=evs)
    assert [e.name for e in mine] == ["Racing Fest"]
    assert calendar.fests_for(["Horror"], dt.date(2026, 10, 9), evs=evs)[0].name.startswith("Steam Scream")


def test_wait_hint_only_when_not_at_record_low(monkeypatch):
    lib, meta = racing_fan()
    soon = sale("Steam Winter Sale", dt.date.today() + dt.timedelta(days=9))
    offline_digest(monkeypatch, events=[soon], history={30: 90, 31: 60})
    cands = {30: item(30, "Could be cheaper", RACING, cut=50), 31: item(31, "At its record", RACING, cut=60)}
    ctx = make_ctx(lib, meta, {}, cands)
    d = engine.build_digest(ctx, limit=10, min_discount=0)
    by = {r.item.appid: r for r in d.picks}
    assert by[30].extras["wait"].name == "Steam Winter Sale" and "wait" not in by[31].extras
    assert d.sale_next is soon
    note = notes_for(by[30])
    assert "⏳" in note and "9" in note


def test_running_sale_and_fests_reach_the_digest(monkeypatch):
    lib, meta = racing_fan()
    today = dt.date.today()
    fest = calendar.Event("Racing Fest", "fest", today + dt.timedelta(days=3), today + dt.timedelta(days=10),
                          ["Racing"])
    offline_digest(monkeypatch, events=[sale("Steam Summer Sale", today - dt.timedelta(days=2)), fest])
    ctx = make_ctx(lib, meta, {}, {40: item(40, "x", RACING)})
    d = engine.build_digest(ctx, limit=5, min_discount=0)
    assert d.sale_now.name == "Steam Summer Sale" and d.fests == [fest]


@pytest.mark.parametrize("country,expected", [("US", True), ("DE", True), ("GB", True), ("CA", True),
                                              ("TR", False), ("AR", False), ("KZ", False), ("RU", False),
                                              ("IN", False), ("BR", False)])
def test_elsewhere_auto_only_without_regional_pricing(country, expected):
    assert itad.elsewhere_enabled("auto", country) is expected
    assert itad.elsewhere_enabled("on", country) and not itad.elsewhere_enabled("off", country)


def test_elsewhere_compares_official_stores(monkeypatch):
    monkeypatch.setattr(config.cfg, "itad_api_key", "k")
    monkeypatch.setattr(itad, "_resolve_ids", lambda ids: {a: f"g{a}" for a in ids})

    def deal(shop_id, name, amount):
        return {"shop": {"id": shop_id, "name": name}, "price": {"amount": amount}, "url": f"https://itad/{shop_id}"}
    monkeypatch.setattr(itad, "request_json", lambda url, params=None, payload=None, **kw: [
        {"id": "g1", "deals": [deal(61, "Steam", 49.99), deal(37, "Humble Store", 39.99), deal(35, "GOG", 44.99)]},
        {"id": "g2", "deals": [deal(61, "Steam", 9.99), deal(16, "Epic", 9.89)]},          # <3%: not worth it
        {"id": "g3", "deals": [deal(61, "Steam", 9.99), deal(999, "Key reseller", 1.00)]},  # unofficial: ignored
    ])
    found = itad.elsewhere([1, 2, 3], "US")
    assert set(found) == {1} and found[1].shop == "Humble" and found[1].pct == 20


def test_notes_are_rendered_in_ui_language(monkeypatch):
    lib, meta = racing_fan()
    offline_digest(monkeypatch, accounts={50: "EA Account"})
    ctx = make_ctx(lib, meta, {}, {50: item(50, "EA game", PUZZLE)})
    rec = engine.build_digest(ctx, limit=5, min_discount=0).picks[0]
    config.cfg.lang = "ru"
    try:
        assert "нужен EA Account" in notes_for(rec)
    finally:
        config.cfg.lang = "en"
