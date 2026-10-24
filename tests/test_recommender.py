import datetime as dt

from steamsift.itad import History, analyze_price_series
from steamsift.prefs import normalize_title
from steamsift.recommender import (Profile, Signal, TagSpace, W_AFFINITY, W_DEAL, W_DEPTH, W_RARITY, W_QUALITY, W_BUNDLE,
                                   calibrate, centered, cosine, deal_value, diversify, make_rec,
                                   wilson_lower, Rec)
from steamsift.steam import Item, _parse_item


def test_wilson_penalises_small_samples():
    assert wilson_lower(100, 5) < wilson_lower(95, 5000)
    assert wilson_lower(None, 0) is None


def test_idf_downweights_ubiquitous_tags():
    space = TagSpace.build([{"Singleplayer": 1, "Racing": 1}] + [{"Singleplayer": 1, "Action": 1}] * 20)
    v = space.vec({"Singleplayer": 100, "Racing": 100})
    assert v["Racing"] > v["Singleplayer"]
    assert abs(sum(x * x for x in v.values()) - 1) < 1e-9


def test_leave_one_out_removes_self_boost():
    space = TagSpace({"A": 1.0, "B": 1.0}, 1.0)
    va, vb = space.vec({"A": 1}), space.vec({"B": 1})
    sigs = [Signal(1, "a", "wishlist", 1.0, va), Signal(2, "b", "played", 1.0, vb)]
    vector = {}
    for s in sigs:
        for t, x in centered(s.vec, space.mean).items():
            vector[t] = vector.get(t, 0) + s.weight * x
    p = Profile(vector, sigs, space.mean)
    assert p.cosine(va, exclude=1) < p.cosine(va)


def test_deal_value_rewards_historic_lows():
    assert deal_value(50, History(50)) > deal_value(50, History(90))


def test_edition_normalisation():
    assert normalize_title("Sekiro™: Shadows Die Twice - GOTY Edition") == normalize_title("Sekiro: Shadows Die Twice")
    assert normalize_title("Mafia II: Definitive Edition") == normalize_title("Mafia II")


def test_diversify_one_per_franchise():
    def rec(aid, fr):
        return Rec(Item(aid, str(aid), franchises=[fr] if fr else []), 0, 0, 0, "", False)
    out = diversify([rec(1, "Wolf"), rec(2, "Wolf"), rec(3, None), rec(4, "Mafia")])
    assert [r.item.appid for r in out] == [1, 3, 4, 2]


def test_cosine_symmetric():
    a, b = {"x": 0.6, "y": 0.8}, {"x": 1.0}
    assert cosine(a, b) == cosine(b, a) == 0.6


def test_cadence_and_analyze_price_series():
    today = dt.date(2026, 6, 15)
    # Rare sale: only 1 sale in the last year (~240 days between sales) and ATL was 3 years ago at 85%
    rows = [
        ((today - dt.timedelta(days=900)).isoformat(), 299, 1999, 85),
        ((today - dt.timedelta(days=890)).isoformat(), 1999, 1999, 0),
        ((today - dt.timedelta(days=250)).isoformat(), 699, 1999, 65),
        ((today - dt.timedelta(days=240)).isoformat(), 1999, 1999, 0),
        ((today - dt.timedelta(days=2)).isoformat(), 599, 1999, 70),
    ]
    stats = analyze_price_series(rows, today=today)
    h = History(**stats)
    assert h.best_cut == 85 and h.low_2y_cut == 70
    assert h.is_2y_low(70) and not h.is_atl(70)
    assert h.tier == "rare"
    assert h.rarity(70) == 1.0


def test_bundle_parsing_and_deal_value():
    raw = {
        "id": 400,
        "success": 1,
        "name": "Portal Complete Bundle",
        "best_purchase_option": {
            "packageid": 1234,
            "bundleid": 5678,
            "purchase_option_name": "Portal Complete Bundle",
            "discount_pct": 80,
            "bundle_discount_pct": 25,
            "final_price_in_cents": "299",
            "original_price_in_cents": "1499",
            "formatted_final_price": "$2.99",
            "formatted_original_price": "$14.99",
            "must_purchase_as_set": False,
            "included_game_count": 2,
        },
    }
    meta, price = _parse_item(raw, {})
    it = Item(**meta, **price)
    assert it.is_bundle and it.complete_the_set and it.bundle_id == 5678
    assert it.package_id == 1234 and it.included_games == 2 and it.bundle_discount == 25
    assert "Complete the Set" in it.bundle_badge(owned_in_set=1)
    assert "25%" in it.bundle_badge(owned_in_set=1)
    assert it.bundle_url.endswith("/bundle/5678/")
    # Bundle + rare ATL gets higher deal value than plain non-bundle cut
    plain = Item(401, "Plain", cut=70, final_cents=599)
    hist_rare = History(best_cut=70, low_2y_cut=70, covered_days=730, sales_2y=1, gap_days=240)
    hist_freq = History(best_cut=85, low_2y_cut=85, covered_days=730, sales_2y=18, gap_days=30)
    assert deal_value(70, hist_rare, it) > deal_value(70, hist_freq, plain)


def test_deal_first_ranking_weights():
    assert W_DEAL == 0.75 and W_AFFINITY == 0.25
    assert abs(W_DEPTH + W_RARITY + W_QUALITY + W_BUNDLE - 1) < 1e-9
    space = TagSpace.build([{"Racing": 100, "Action": 50}, {"Puzzle": 100, "Indie": 80}])
    v_race = space.vec({"Racing": 100, "Action": 50})
    p = Profile(v_race, [Signal(1, "Dirt", "played", 1.0, v_race)], space.mean)
    # Candidate A: mediocre deal on a racing game; Candidate B: phenomenal ATL bundle deal on a top-rated puzzle game
    a = Item(10, "Racer", cut=30, final_cents=1999, review_pct=75, review_count=200,
             tags={"Racing": 100, "Action": 50})
    b = Item(20, "Masterpiece Bundle", cut=85, final_cents=299, review_pct=98, review_count=25000,
             tags={"Puzzle": 100, "Indie": 80}, bundle_id=99, included_games=3, bundle_discount=20,
             complete_the_set=True)
    ra = make_rec(a, p, space, is_wish=False)
    rb = make_rec(b, p, space, is_wish=False)
    ra.hist = History(best_cut=75, low_2y_cut=75, covered_days=730, sales_2y=16, gap_days=35)
    rb.hist = History(best_cut=85, low_2y_cut=85, covered_days=730, sales_2y=1, gap_days=300)
    calibrate([ra, rb])
    recs = sorted([ra, rb], key=lambda r: -r.score)
    assert recs[0].item.appid == 20
    assert recs[0].deal_score > recs[1].deal_score
    assert recs[0].is_atl and recs[0].is_2y_low and recs[0].is_rare_sale
    assert 0 <= recs[0].taste_pct <= 100

