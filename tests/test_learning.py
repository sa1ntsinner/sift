"""G4: cold-start seeds, click/info interest, ⊘ hides and target prices change ranking."""
from helpers import HORROR, PUZZLE, SHOOTER, item, library, make_ctx, offline_digest, racing_fan
from steamsift import engine, prefs


def _affinity(ctx, it):
    return ctx.profile.cosine(ctx.space.vec(it.tags), exclude=it.appid)


def test_seeds_give_a_new_account_a_taste():
    lib = library({})                                   # brand-new account, nothing played
    meta = {7: item(7, "Bloodborne-like", HORROR), 8: item(8, "Another horror", HORROR)}
    puzzle, horror = item(20, "Puzzle", PUZZLE), item(21, "Horror", HORROR)
    cold = make_ctx(lib, meta, {}, {20: puzzle, 21: horror})
    seeded = make_ctx(lib, meta, {}, {20: puzzle, 21: horror}, seeds=[7, 8])
    assert not cold.profile.top_tags(3)
    assert seeded.profile.top_tags(3)[0][0] in ("Horror", "Survival Horror")
    assert _affinity(seeded, horror) > _affinity(seeded, puzzle)
    assert any(a.kind == "seed" for a in seeded.profile.anchors), "seeds can explain picks (“like X”)"


def test_interest_from_opening_games_nudges_taste():
    lib, meta = racing_fan()
    meta[30] = item(30, "Shooter I opened", SHOOTER)
    shooter = item(31, "Another shooter", SHOOTER)
    base = make_ctx(lib, meta, {}, {31: shooter})
    curious = make_ctx(lib, meta, {}, {31: shooter}, interest={30: 3})
    assert _affinity(curious, shooter) > _affinity(base, shooter)


def test_hidden_for_taste_is_negative_but_owned_is_neutral():
    lib, meta = racing_fan()
    meta[40] = item(40, "Horror I dislike", HORROR)
    other = item(41, "Similar horror", HORROR)
    base = make_ctx(lib, meta, {}, {41: other})
    taste = make_ctx(lib, meta, {}, {41: other}, hidden={40: {"name": "x", "reason": "taste", "at": 0}})
    owned = make_ctx(lib, meta, {}, {41: other}, hidden={40: {"name": "x", "reason": "owned", "at": 0}})
    assert _affinity(taste, other) < _affinity(base, other)
    assert abs(_affinity(owned, other) - _affinity(base, other)) < 1e-9


def test_prefs_roundtrip_feedback_and_targets():
    prefs.log_feedback(555, "open")
    prefs.log_feedback(555, "info")
    assert prefs.interest()[555] == 3                    # open counts double
    prefs.set_target(556, "Game", 999)
    prefs.set_target(557, "Other", None)
    assert prefs.targets()[556]["price_cents"] == 999 and prefs.targets()[557]["price_cents"] is None
    assert prefs.remove_target(556) and 556 not in prefs.targets()


def test_target_price_hit_boosts_and_is_flagged(monkeypatch):
    lib, meta = racing_fan()
    lib.wishlist = [{"appid": 60, "priority": 0, "date_added": 0}, {"appid": 61, "priority": 0, "date_added": 0}]
    wish = {60: item(60, "Hit", PUZZLE, price=500), 61: item(61, "Miss", PUZZLE, price=500)}
    offline_digest(monkeypatch, history={61: 90})
    prefs.set_target(60, "Hit", 600)                     # 5.00 <= 6.00 → hit
    prefs.set_target(61, "Miss", None)                   # "lowest" but best ever is −90%, now −50% → no
    try:
        ctx = make_ctx(lib, meta, wish, {})
        d = engine.build_digest(ctx, limit=10, min_discount=0)
        by = {r.item.appid: r for r in d.wish}
        assert by[60].extras["target"]["hit"] and not by[61].extras["target"]["hit"]
        assert by[60].score > by[61].score
    finally:
        prefs.remove_target(60)
        prefs.remove_target(61)

