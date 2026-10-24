"""G3: preference filters change recommendations correctly."""
import pytest

from helpers import HORROR, PUZZLE, RACING, item, make_ctx, offline_digest, racing_fan
from steamsift import config, engine
from steamsift.config import Filters
from steamsift.engine import passes_filters


@pytest.mark.parametrize("filters,overrides,ok", [
    (Filters(), {}, True),
    (Filters(game_lang="audio", game_lang_name="russian"), {"languages": {"8": 3}}, False),   # subs only
    (Filters(game_lang="audio", game_lang_name="russian"), {"languages": {"8": 7}}, True),
    (Filters(game_lang="subs", game_lang_name="russian"), {"languages": {"0": 7}}, False),    # no Russian
    (Filters(game_lang="subs", game_lang_name="russian"), {"languages": {}}, True),           # unknown → keep
    (Filters(deck="verified"), {"deck": 2}, False),
    (Filters(deck="playable"), {"deck": 2}, True),
    (Filters(deck="playable"), {"deck": 1}, False),
    (Filters(platforms=["linux"]), {"platforms": ["windows"]}, False),
    (Filters(platforms=["linux", "mac"]), {"platforms": ["windows", "mac"]}, True),
    (Filters(), {"content": [3]}, False),                                                      # adult hidden
    (Filters(adult=True), {"content": [3, 4]}, True),
    (Filters(early_access="hide"), {"tags": {"Early Access": 900, **RACING}}, False),
    (Filters(), {"tags": {"Early Access": 900, **RACING}}, True),
    (Filters(), {"vr_only": True}, False),
    (Filters(vr_only=True), {"vr_only": True}, True),
    (Filters(exclude_tags=["Horror"]), {"tags": HORROR}, False),
    (Filters(exclude_tags=["Horror"]), {"tags": RACING}, True),
    (Filters(min_reviews=10_000), {"review_count": 9_999}, False),
    (Filters(min_positive=95), {"review_pct": 92}, False),
])
def test_passes_filters(filters, overrides, ok):
    assert passes_filters(item(10, "X", **overrides), filters) is ok


def test_game_language_defaults_to_ui_language():
    f = Filters(game_lang="subs")
    assert passes_filters(item(1, "X", languages={"8": 1}), f, "russian")
    assert not passes_filters(item(1, "X", languages={"8": 1}), f, "turkish")


def _digest_ids(ctx, **kw):
    d = engine.build_digest(ctx, limit=20, min_discount=0, **kw)
    return [r.item.appid for r in d.picks]


def test_filters_applied_to_picks_not_wishlist(monkeypatch):
    lib, meta = racing_fan()
    lib.wishlist = [{"appid": 50, "priority": 0, "date_added": 0}]
    wish = {50: item(50, "Wished VR racer", RACING, vr_only=True)}
    cands = {60: item(60, "VR racer", RACING, vr_only=True), 61: item(61, "Flat racer", RACING)}
    offline_digest(monkeypatch)
    ctx = make_ctx(lib, meta, wish, cands)
    d = engine.build_digest(ctx, limit=20, min_discount=0)
    assert [r.item.appid for r in d.picks] == [61]
    assert [r.item.appid for r in d.wish] == [50], "your explicit wishlist is never filtered"


def test_third_party_accounts_filter(monkeypatch):
    lib, meta = racing_fan()
    cands = {70: item(70, "Needs EA", RACING), 71: item(71, "Plain", RACING)}
    offline_digest(monkeypatch, accounts={70: "EA Account"})
    ctx = make_ctx(lib, meta, {}, cands)
    assert set(_digest_ids(ctx)) == {70, 71}
    rec = next(r for r in engine.build_digest(ctx, limit=20, min_discount=0).picks if r.item.appid == 70)
    assert rec.extras["account"] == "EA Account"
    config.cfg.profile.filters.third_party = False
    try:
        assert _digest_ids(ctx) == [71]
    finally:
        config.cfg.profile.filters.third_party = True


def test_budget_and_min_discount(monkeypatch):
    lib, meta = racing_fan()
    cands = {80: item(80, "Cheap", RACING, price=300, cut=80), 81: item(81, "Pricey", RACING, price=3000, cut=80),
             82: item(82, "Small cut", RACING, price=300, cut=10)}
    offline_digest(monkeypatch)
    ctx = make_ctx(lib, meta, {}, cands)
    d = engine.build_digest(ctx, limit=20, min_discount=20, budget=10.0)
    assert [r.item.appid for r in d.picks] == [80]


def test_owned_family_and_hidden_are_excluded(monkeypatch):
    lib, meta = racing_fan()
    lib.family_games = {90: {"name": "Shared racer", "owner": "sam"}, 91: {"name": "Unshareable", "owner": "sam"}}
    cands = {1: item(1, "Assetto Corsa", RACING), 90: item(90, "Shared racer", RACING),
             91: item(91, "Unshareable", RACING), 92: item(92, "Hidden racer", RACING),
             93: item(93, "Assetto Corsa - Ultimate Edition", RACING), 94: item(94, "Fresh racer", RACING)}
    offline_digest(monkeypatch)
    ctx = make_ctx(lib, meta, {}, cands, hidden={92: {"name": "Hidden racer", "reason": "owned", "at": 0}},
                   unshared={91})
    ids = _digest_ids(ctx)
    assert set(ids) == {91, 94}, ids
    rec = next(r for r in engine.build_digest(ctx, limit=20, min_discount=0).picks if r.item.appid == 91)
    assert rec.extras["unshared"] == "sam"


def test_explore_prefers_less_familiar_games(monkeypatch):
    lib, meta = racing_fan()
    clone = item(100, "Clone racer", RACING)
    blend = item(101, "Racing horror", {"Racing": 900, "Horror": 900, "Atmospheric": 600, "Driving": 400})
    offline_digest(monkeypatch)

    def gap(explore):
        config.cfg.profile.filters.explore = explore
        ctx = make_ctx(lib, meta, {}, {100: clone, 101: blend, 102: item(102, "Puzzle", PUZZLE)})
        recs = {r.item.appid: r for r in engine.build_digest(ctx, limit=20, min_discount=0).picks}
        return recs[100].score - recs[101].score
    try:
        assert gap(1.0) < gap(0.0), "exploring lowers near-clones relative to new-but-related games"
    finally:
        config.cfg.profile.filters.explore = 0.15
