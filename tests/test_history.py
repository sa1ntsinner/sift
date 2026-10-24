"""Real ITAD log, request/cache, verdict and objective-score contracts."""
import datetime as dt
import re
import json
import time
from dataclasses import asdict, replace
from pathlib import Path

import pytest
import requests

from steamsift import db, itad, net
from steamsift.calendar import Event
from steamsift.cli import _rec_to_dict
from steamsift.itad import Bundle, History, parse_bundles, parse_history
from steamsift.query import Query, parse
from steamsift.recommender import Rec, Verdict, verdict
from steamsift.steam import Item

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = dt.date(2026, 10, 24)
NOW = dt.datetime(2026, 10, 24, tzinfo=dt.timezone.utc)


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def change(days, cut, regular=1000):
    return {"timestamp": (TODAY - dt.timedelta(days=days)).isoformat(), "shop": {"id": 61},
            "deal": {"cut": cut, "regular": {"amountInt": regular}}}


@pytest.mark.parametrize("name,tier,sales,low,gap", [
    ("re2", "frequent", 19, 80, 43),
    ("bioshock", "frequent", 18, 75, 42),
    ("stardew", "regular", 11, 50, 68),
    ("bg3", "frequent", 18, 30, 38),
    ("disco", "frequent", 21, 90, 36),
])
def test_recorded_history(name, tier, sales, low, gap):
    log = fixture(f"itad_history_{name}.json")
    today = max(dt.datetime.fromisoformat(r["timestamp"]).date() for r in log)
    h = parse_history(log, today)
    assert (h.tier, h.sales_2y, h.low_2y_cut, h.gap_days) == (tier, sales, low, gap)
    assert h.covered_days > 1000
    assert h.low_1y_cut <= h.low_2y_cut <= h.best_cut
    assert h.points == sorted(h.points, key=lambda p: p[0])
    assert all(0 <= (today - dt.date.fromisoformat(day)).days <= 730 for day, _ in h.points)
    assert h == parse_history(list(reversed(log)), today)


def test_open_sales_and_cut_changes_are_one_event():
    rows = [change(900, 0), change(700, 50), change(690, 60), change(680, 0),
            change(500, 40), change(490, 0), change(10, 70), change(1, 80)]
    h = parse_history(rows, TODAY, store_low_cut=90)
    assert (h.sales_2y, h.gap_days, h.typical_cut, h.since_last_days) == (2, 200, 50, 490)
    assert (h.best_cut, h.low_1y_cut, h.low_2y_cut) == (90, 80, 80)
    assert h.tier == "rare"
    closed = parse_history(rows + [change(0, 0)], TODAY)
    assert (closed.sales_2y, closed.typical_cut, closed.since_last_days) == (3, 60, 0)
    assert closed.gap_days == 345


def test_window_lows_carry_forward_without_counting_old_start():
    h = parse_history([change(900, 0), change(800, 85), change(600, 0),
                       change(400, 70), change(300, 0)], TODAY)
    assert (h.low_2y_cut, h.low_1y_cut, h.sales_2y) == (85, 70, 1)
    assert h.points[0] == ((TODAY - dt.timedelta(days=730)).isoformat(), 85)
    assert parse_history([change(900, 0)], TODAY).low_2y_cut == 0


def test_raises_fake_discount_and_ignored_bad_rows():
    h = parse_history([change(900, 0), change(80, 0, 1200), change(30, 50, 1400)], TODAY)
    assert h.raised_days == 30 and h.fake_discount(50) and not h.fake_discount(0)
    assert not replace(h, raised_days=61).fake_discount(50)
    assert replace(h, raised_days=60).fake_discount(1)
    assert replace(h, raised_days=0).fake_discount(1)
    assert not parse_history([change(900, 0), change(121, 50, 2000)], TODAY).fake_discount(50)
    assert parse_history([{}, {"timestamp": "bad", "deal": {}},
                          dict(change(1, 99), shop={"id": 6})], TODAY) == History()


def test_history_methods_and_tier_boundaries():
    assert not History(80).is_atl(79)
    assert History(80).is_atl(80)
    assert History(90, low_2y_cut=70).is_2y_low(70)
    assert not History(90, low_2y_cut=70).is_2y_low(69)
    assert not History().is_2y_low(0)
    assert History(80).tier == "unknown"
    assert History(80, covered_days=364, sales_2y=2, gap_days=20).tier == "unknown"
    assert History(80, covered_days=365, gap_days=45).tier == "frequent"
    assert History(80, covered_days=539, sales_2y=2).tier == "regular"
    assert History(80, covered_days=540, sales_2y=2).tier == "rare"
    assert History(80, covered_days=730, sales_2y=12).tier == "frequent"
    assert History(80).rarity(50) == 0.4
    assert History(80).rarity(80) == pytest.approx(0.6)


@pytest.mark.parametrize("cut,h,extra,expected", [
    (80, History(80, raised_days=2), {}, Verdict("nope", "fake", 2)),
    (80, History(80), {}, Verdict("ok", "atl_unknown", 80)),                  # no log: can't call it rare
    (80, History(80, sales_2y=3, gap_days=200, covered_days=730), {}, Verdict("hot", "atl", 80)),
    (80, History(80, sales_2y=19, gap_days=43, covered_days=730), {}, Verdict("great", "returns", 43)),
    (80, History(80, sales_2y=14, covered_days=730), {}, Verdict("great", "returns", 52)),
    (70, History(90, low_2y_cut=70), {}, Verdict("hot", "low_2y", 70)),
    (60, History(90, typical_cut=60, sales_2y=2, covered_days=730), {}, Verdict("hot", "rare", 2)),
    (50, History(60, typical_cut=55),
     {"sale_next": Event("Winter", "sale", TODAY + dt.timedelta(days=21), TODAY + dt.timedelta(days=30))},
     Verdict("meh", "sale_soon", 21)),
    (75, History(90, covered_days=400), {}, Verdict("nope", "cheaper_before", 60)),     # $25 vs $10
    (75, History(80, covered_days=400), {}, Verdict("meh", "cheaper_before", 20)),      # $25 vs $20
    (89, History(90, typical_cut=70, covered_days=400), {}, Verdict("ok", "typical", 70)),
    (89, History(90, covered_days=400), {}, Verdict("ok", "typical", 90)),
    (50, None, {}, Verdict()),
    (0, History(90), {}, Verdict()),
    (50, History(), {}, Verdict()),
])
def test_every_verdict_rule(cut, h, extra, expected):
    assert verdict(cut, h, today=TODAY, **extra) == expected


def test_prices_not_percentages_decide_when_the_base_price_moved():
    # was $10 at −50% ($5); now the base price is $15, at −60% that is $6: deeper cut, higher price
    h = History(50, low_cents=500, regular_cents=1500, covered_days=730, sales_2y=6, gap_days=100)
    assert not h.is_atl(60) and h.cheaper_pct(60) == 17
    assert verdict(60, h, today=TODAY) == Verdict("meh", "cheaper_before", 17)
    assert h.is_atl(67)                                       # $4.95 beats the old $5
    # the base price went down from $20 to $10: −50% now ($5) equals the old −75% record
    down = History(75, low_cents=500, regular_cents=1000, covered_days=730, sales_2y=3, gap_days=200)
    assert down.is_atl(50) and verdict(50, down, today=TODAY).kind == "hot"
    # within a dollar of the record: not worth waiting for
    close = History(90, low_cents=199, regular_cents=1999, covered_days=730, sales_2y=8, gap_days=80)
    assert verdict(88, close, today=TODAY) == Verdict("ok", "typical", 90)     # $2.40 vs $1.99


def test_verdict_precedence_bundle_and_sale_boundaries():
    h = History(60, covered_days=730, sales_2y=15, low_2y_cut=55, typical_cut=55)
    b = Bundle("Active", "Humble", "url", 300, "USD", "2099-01-01T00:00:00+00:00")
    args = {"bundle": b, "price_cents": 500, "currency": "USD", "today": TODAY}
    assert verdict(50, h, **args) == Verdict("hot", "bundle", 300)
    assert verdict(60, h, **args).reason == "returns"          # frequent record price: comes back
    assert verdict(50, replace(h, raised_days=1), **args).reason == "fake"
    no_bundle = dict(args, bundle=None)
    for days, reason in [(21, "sale_soon"), (22, "cheaper_before"), (-1, "cheaper_before")]:
        sale = Event("Sale", "sale", TODAY + dt.timedelta(days=days), TODAY + dt.timedelta(days=40))
        assert verdict(50, h, sale_next=sale, **no_bundle).reason == reason
    assert verdict(50, h, sale_next=Event("Fest", "fest", TODAY, TODAY), **no_bundle).reason == "cheaper_before"
    assert verdict(50, h, **dict(args, currency="EUR")).reason == "cheaper_before"
    assert verdict(50, h, **dict(args, price_cents=300)).reason == "cheaper_before"
    expired = replace(b, expiry_iso="2000-01-01T00:00:00+00:00")
    assert verdict(50, h, **dict(args, bundle=expired)).reason == "cheaper_before"


def bundle_entry(expiry="2027-01-01T00:00:00Z", publish="2026-01-01T00:00:00Z"):
    return {"title": "Bundle", "page": {"name": "Humble"}, "url": "https://example.com", "expiry": expiry,
            "publish": publish, "tiers": [
                {"price": {"amountInt": 100, "currency": "USD"}, "games": [{"id": "other"}]},
                {"price": {"amountInt": 300, "currency": "USD"}, "games": [{"id": "gid"}]},
                {"price": {"amountInt": 400, "currency": "USD"}, "games": [{"id": "gid"}]}]}


def test_bundle_tier_and_activity_filtering():
    assert parse_bundles([bundle_entry()], "gid", NOW).price_cents == 300
    assert parse_bundles([bundle_entry(expiry=None)], "gid", NOW)
    assert not parse_bundles([bundle_entry(expiry=None, publish="2020-01-01T00:00:00Z")], "gid", NOW)
    assert not parse_bundles([bundle_entry(expiry=NOW.isoformat())], "gid", NOW)
    assert not parse_bundles([bundle_entry(publish="2027-01-01T00:00:00Z")], "gid", NOW)
    assert not parse_bundles([bundle_entry()], "absent", NOW)
    ids = fixture("itad_ids.json")
    for name, aid in [("re2", 883710), ("bioshock", 7670), ("stardew", 413150), ("bg3", 1086940), ("disco", 632470)]:
        assert parse_bundles(fixture(f"itad_bundles_{name}.json"), ids[str(aid)],
                             dt.datetime(2100, 1, 1, tzinfo=dt.timezone.utc)) is None


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(itad, "_key", lambda: "test-key")
    for c in db.Cache.all:
        c._data, c._dirty = {}, set()
    for aid, gid in fixture("itad_ids.json").items():
        itad._id_cache.set(int(aid), gid)
    monkeypatch.setattr(itad, "price_history", lambda *args: [])


def test_fetch_split_prices_cache_incremental_merge_and_failure(api, monkeypatch):
    calls = []
    log = [change(900, 0), change(50, 60), change(40, 0)]

    def request(url, params=None, payload=None, **kwargs):
        calls.append((url, params, payload))
        if "prices/v3" in url:
            return fixture("itad_prices_v3.json")
        assert "history/v2" in url
        return log

    monkeypatch.setattr(itad, "request_json", request)
    ids = [883710, 7670]
    result = itad.history(ids, deep=[883710])
    assert result[883710].covered_days == 900
    assert result[7670].covered_days == 0 and result[7670].tier == "unknown"
    assert result[7670].best_cut > 0
    assert len(calls) == 2
    since = calls[-1][1]["since"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", since)   # ITAD answers 400 to fractional seconds
    assert (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(since)).days >= 1095
    itad.history(ids, deep=[883710])
    assert len(calls) == 2
    itad._hist_cache._data = {}
    itad.history(ids, deep=[883710])
    assert len(calls) == 2  # raw log is fresh for 3 days
    itad._hist_cache._data = {}
    cached = itad._log_cache.get(883710)
    cached["fetched"] = time.time() - 73 * 3600
    log = [log[-1], change(1, 75)]
    itad.history(ids, deep=[883710])
    assert calls[-1][1]["since"] == itad._timestamp(change(40, 0)["timestamp"]).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert len(itad._log_cache.get(883710)["log"]) == 4
    itad._hist_cache._data = {}
    itad._log_cache.get(883710)["fetched"] = 0
    monkeypatch.setattr(itad, "request_json", lambda *a, **kw: None)
    assert itad.history(ids, deep=[883710])[883710].covered_days == 900


def test_no_key_empty_paths_and_local_fallback(api, monkeypatch):
    monkeypatch.setattr(itad, "request_json", lambda *args, **kw: None)
    monkeypatch.setattr(itad, "price_history", lambda *args: [(change(900, 0)["timestamp"], 1000, 1000, 0),
                                                               (change(1, 60)["timestamp"], 400, 1000, 60)])
    assert itad.history([883710])[883710].best_cut == 60
    assert itad.bundles([883710]) == {}
    assert itad.history([]) == {}
    monkeypatch.setattr(itad, "_key", lambda: "")
    assert itad.history([883710]) == itad.bundles([883710]) == {}


def test_bundles_fetch_and_cache(api, monkeypatch):
    gid = fixture("itad_ids.json")["883710"]
    entry = bundle_entry(expiry="2099-01-01T00:00:00Z")
    for tier in entry["tiers"][1:]:
        tier["games"] = [{"id": gid}]
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        return [entry]

    monkeypatch.setattr(itad, "request_json", request)
    assert itad.bundles([883710])[883710].price_cents == 300
    assert itad.bundles([883710])[883710].shop == "Humble"
    assert len(calls) == 1


@pytest.mark.parametrize("after", ["2", "Sat, 24 Oct 2099 00:00:00 GMT", "invalid"])
def test_429_retry_after_once(api, monkeypatch, after):
    calls, waits = [], []

    def request(*args, **kwargs):
        calls.append(1)
        response = requests.Response()
        response.status_code = 429
        response.headers["Retry-After"] = after
        return response

    monkeypatch.setattr(net.SESSION, "get", request)
    monkeypatch.setattr(net.time, "sleep", waits.append)
    monkeypatch.setattr(net, "_hold", {})
    assert itad._request("https://example.com") is None
    if after == "2" or after == "invalid":                  # short wait: sleep once, retry once
        assert len(calls) == 2 and waits == [2 if after == "2" else 1.0]
    else:                                                   # a long hold: no sleeping, the host is skipped
        assert len(calls) == 1 and waits == []
        assert itad._request("https://example.com/again") is None and len(calls) == 1


def test_deal_score_verdict_json_buy_filter_and_aliases():
    r = Rec(Item(1, "Test", cut=50, final_cents=500), 0, 0.8, 0, "", False,
            hist=History(80, covered_days=400), affinity=0.4)
    r.rescore()
    depth = 0.5 * (0.5 ** 0.9) + 0.5 * (50 / 80) ** 1.5
    assert r.deal_score == round(100 * (0.45 * depth + 0.2 * 0.5 + 0.25 * 0.8), 1)
    assert r.score == round(0.75 * r.deal_score + 0.25 * 40, 1)
    base = r.deal_score
    r.hist.raised_days = 10
    r.rescore()
    assert r.deal_score == pytest.approx(base * 0.6, abs=0.1)
    assert _rec_to_dict(r)["verdict"] == asdict(r.verdict)
    assert _rec_to_dict(r)["history"]["covered_days"] == 400
    assert Query(buy=True, min_cut=0, max_price=0).apply([r]) == []
    r.item.cut = 80
    r.hist.raised_days = -1
    r.rescore()
    assert parse("--buy").buy
    assert Query(buy=True, min_cut=0, max_price=0).apply([r]) == [r]
    for old in ["score", "atl", "rarity", "deal_value"]:
        assert parse(f"--sort {old}").sort == "deal"
    assert parse("--sort taste").sort == "match"
    assert parse("--sort discount").sort == "cut"


def test_engine_passes_full_ids_and_shortlist_and_attaches_bundle(monkeypatch):
    from helpers import item, make_ctx, offline_digest, racing_fan
    from steamsift import config, engine
    monkeypatch.setattr(config.cfg, "country", "US")
    lib, meta = racing_fan()
    offline_digest(monkeypatch)
    items = {30: item(30, "Deep", cut=50, price=500), 31: item(31, "Shallow", cut=50, price=500)}
    ctx = make_ctx(lib, meta, candidates=items)
    recs = [ctx.rec(it, False) for it in items.values()]
    seen = []
    b = Bundle("Active", "Humble", "url", 100, "USD", "2099-01-01T00:00:00Z")

    def history(ids, deep=None):
        seen.append((ids, deep))
        return {30: History(90, covered_days=730, sales_2y=15), 31: History(90)}

    def bundles(ids):
        assert ids == [30]
        return {30: b}

    monkeypatch.setattr(itad, "history", history)
    monkeypatch.setattr(itad, "bundles", bundles)
    engine.enrich(recs, ctx, deep=[recs[0]])
    assert seen == [([30, 31], [30])]
    assert recs[0].extras["bundle3p"] is b
    assert "bundle3p" not in recs[1].extras
    assert recs[0].verdict == Verdict("hot", "bundle", 100)
    assert recs[1].hist.tier == "unknown"


def test_request_recovers_after_429_and_exceptions_are_safe(api, monkeypatch):
    calls, waits = [], []

    def get(*args, **kwargs):
        response = requests.Response()
        response.status_code = 429 if not calls else 200
        response.headers["Retry-After"] = "3"
        response._content = b"[]"
        calls.append(1)
        return response

    monkeypatch.setattr(net.SESSION, "get", get)
    monkeypatch.setattr(net.time, "sleep", waits.append)
    monkeypatch.setattr(net, "_hold", {})
    assert itad._request("https://example.com") == []
    assert len(calls) == 2 and waits == [3]

    def broken(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(itad, "request_json", broken)
    assert itad.history([883710])[883710] == History()
    assert itad.bundles([883710]) == {}
