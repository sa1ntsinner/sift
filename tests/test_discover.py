"""Discover: acclaimed, well-discounted games from genres you don't play — never like ones you dropped."""
import datetime as dt

import pytest

from helpers import HORROR, PUZZLE, RACING, SHOOTER, item, library, make_ctx, offline_digest, racing_fan
from steamsift import discover as disc, engine, prefs

TACTICS = {"Turn-Based Tactics": 1000, "Strategy": 800, "Sci-fi": 600, "Tactical": 500, "Atmospheric": 300}
FIGHT = {"Fighting": 1000, "Arcade": 800, "Action": 600, "2D Fighter": 500, "Competitive": 300}


@pytest.fixture(autouse=True)
def fresh_weeks():
    disc._seen._data, disc._seen._dirty = {}, set()


@pytest.fixture
def world(monkeypatch):
    lib, meta = racing_fan()
    meta[80] = item(80, "Brawler I hid", FIGHT)
    cands = {
        60: item(60, "Rally Kings", RACING, cut=80),                                   # your genre → a pick
        70: item(70, "Tiny Puzzle", PUZZLE, cut=70, review_pct=97, review_count=3000),
        73: item(73, "Another Puzzle", PUZZLE, cut=60, review_pct=95, review_count=900),
        71: item(71, "Space Tactics", TACTICS, cut=75, review_pct=94, review_count=20000),
        72: item(72, "Bad Shooter", SHOOTER, cut=90, review_pct=55, review_count=5000),  # not good enough
        74: item(74, "Fight Night", FIGHT, cut=80, review_pct=96, review_count=9000),   # like a game you hid
        75: item(75, "Tiny Discount Puzzle", PUZZLE, cut=10, review_pct=98, review_count=4000),  # not a deal
    }
    offline_digest(monkeypatch, history={70: 70, 73: 75, 71: 80})
    ctx = make_ctx(lib, meta, {}, cands, hidden={80: {"name": "Brawler I hid", "reason": "taste", "at": 0}})
    yield ctx
    prefs.clear_hidden()


def ids(recs):
    return [r.item.appid for r in recs]


def test_discover_finds_new_good_deals_and_skips_the_familiar(world):
    d = engine.build_digest(world, limit=20, min_discount=0, discover=True)
    found = ids(d.discover)
    assert set(found) == {70, 71, 73}
    assert 60 in ids(d.picks) and 60 not in found          # racing is your usual → regular pick
    assert all(r.mode == "discover" for r in d.discover)
    assert all(r.mode == "taste" for r in d.picks)          # discover never re-scores the picks


def test_one_list_best_first_but_varied(world):
    d = engine.build_digest(world, limit=20, min_discount=0, discover=True)
    lanes = [r.lane for r in d.discover]
    assert lanes[0] != lanes[1] and lanes.count("Puzzle") == 2   # never two puzzles in a row here
    assert all("new for you" in r.why for r in d.discover)
    assert next(r for r in d.discover if r.item.appid == 70).extras.get("gem")


def test_arrange_spacing_and_franchise_repeats():
    from steamsift.recommender import Rec

    def rec(appid, lane, score, fr=None):
        it = item(appid, f"g{appid}", PUZZLE, franchises=[fr] if fr else [])
        return Rec(item=it, cos=0, quality=0, intent=0, why="", is_wish=False, score=score, lane=lane, mode="discover")
    out = disc.arrange([rec(1, "A", 99), rec(2, "A", 98), rec(3, "A", 97), rec(4, "B", 60), rec(5, "C", 50),
                        rec(6, "B", 96, fr="Saga"), rec(7, "C", 95, fr="Saga")])
    assert [r.item.appid for r in out] == [1, 6, 5, 2, 3, 4, 7]   # varied first, then by score; sequel last


def test_discovery_score_rewards_quality_deal_and_novelty(world):
    d = engine.build_digest(world, limit=20, min_discount=0, discover=True)
    for r in d.discover:
        assert 0 < r.score <= 100 and disc.NOVELTY_MIN <= r.novelty <= 1


def test_shown_last_week_and_ignored_fades(world):
    last_week = dt.date.today() - dt.timedelta(days=7)
    first = engine.build_digest(world, limit=20, min_discount=0, discover=True, today=last_week)
    before = {r.item.appid: r.score for r in first.discover}
    now = engine.build_digest(world, limit=20, min_discount=0, discover=True)
    after = {r.item.appid: r.score for r in now.discover}
    assert all(after[a] < before[a] for a in before)


def test_opened_games_do_not_fade(world):
    last_week = dt.date.today() - dt.timedelta(days=7)
    engine.build_digest(world, limit=20, min_discount=0, discover=True, today=last_week)
    world.interest = {70: 2}
    now = {r.item.appid: r.penalty for r in engine.build_digest(world, limit=20, min_discount=0,
                                                                 discover=True).discover}
    assert now[70] == 1.0 and now[71] < 1.0


def test_frontier_rotates_weekly_and_never_offers_your_genres():
    lib, meta = racing_fan()
    ctx = make_ctx(lib, meta)
    a = disc.frontier(ctx.profile, today=dt.date(2026, 10, 5))
    b = disc.frontier(ctx.profile, today=dt.date(2026, 10, 12))
    assert len(a) == 6 and "Racing" not in a and a != b


def test_lane_prefers_specific_genre_you_dont_play():
    lib, meta = racing_fan()
    ctx = make_ctx(lib, meta, candidates={1: item(1, "x", HORROR)})
    tags = {"Metroidvania": 900, "Platformer": 1000, "Action": 800, "Racing": 950}
    assert disc.lane_of(tags, {"Racing"}, ctx.space) in ("Metroidvania", "Platformer")
    assert disc.lane_of({"Racing": 1000}, {"Racing"}, ctx.space) == ""


def test_empty_profile_does_not_crash():
    ctx = make_ctx(library(), {}, candidates={70: item(70, "Tiny Puzzle", PUZZLE, review_pct=97,
                                                        review_count=3000)})
    recs = [ctx.rec(i, False) for i in ctx.candidates.values()]
    from steamsift.recommender import calibrate
    calibrate(recs)
    assert ids(disc.candidates(recs, ctx.profile, ctx.space)) == [70]


def test_sub_genres_of_what_you_play_are_not_new():
    lib, meta = racing_fan()
    meta[4] = item(4, "Outlast", HORROR)
    lib.my_games[4] = {"appid": 4, "name": "Outlast", "playtime_forever": 100 * 60, "playtime_2weeks": 0,
                       "rtime_last_played": lib.my_games[1]["rtime_last_played"]}
    ctx = make_ctx(lib, meta)
    known = disc.known_tags(ctx.profile)
    assert {"Survival Horror", "Psychological Horror"} <= known and "Metroidvania" not in known
