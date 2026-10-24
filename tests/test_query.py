"""One query model behind `sift` flags, the app's filters and macros."""
import time

import pytest

from helpers import PUZZLE, RACING, item
from steamsift import cli, config, query
from steamsift.itad import History
from steamsift.query import Query, QueryError


class R:                                  # the bits of a Rec that filtering looks at
    def __init__(self, it, hist=None, score=50.0, deal_score=50.0, affinity=0.5):
        self.item, self.hist, self.score, self.mode = it, hist, score, "taste"
        self.deal_score = deal_score
        self.affinity = affinity
        self.taste_pct = round(affinity * 100)
        self.is_atl = bool(hist and hist.is_atl(it.cut))
        self.is_2y_low = bool(hist and hist.is_2y_low(it.cut))
        self.is_rare_sale = bool(hist and hist.tier == "rare")
        self.owned_in_set = 0
        self.extras = {}


@pytest.fixture
def tags(monkeypatch):
    from steamsift import steam
    names = {1: "Indie", 2: "Horror", 3: "Puzzle", 4: "Racing", 5: "Roguelike", 6: "RPG", 7: "Strategy"}
    ru = {1: "Инди", 2: "Хоррор", 3: "Головоломка", 4: "Гонки", 5: "Рогалик", 6: "Ролевая игра", 7: "Стратегия"}
    monkeypatch.setattr(steam, "tag_names", lambda lang="english": ru if lang == "russian" else names)


def test_price_cut_lowest_tags_and_rating():
    cheap = item(1, "Cheap indie", {**PUZZLE, "Indie": 900}, cut=80, price=199)
    pricey = item(2, "Pricey", RACING, cut=50, price=2999, review_pct=70)
    rs = [R(cheap, History(80)), R(pricey, History(90))]
    assert [r.item.name for r in Query(max_price=2).apply(rs)] == ["Cheap indie"]
    assert [r.item.name for r in Query(lowest=True).apply(rs)] == ["Cheap indie"]     # −50 vs −90 isn't a low
    assert [r.item.name for r in Query(tags=["indie"]).apply(rs)] == ["Cheap indie"]
    assert [r.item.name for r in Query(tags=["Indie|Racing"]).apply(rs)] == ["Cheap indie", "Pricey"]
    assert [r.item.name for r in Query(no_tags=["Racing"]).apply(rs)] == ["Cheap indie"]
    assert [r.item.name for r in Query(min_rating=80).apply(rs)] == ["Cheap indie"]
    assert [r.item.name for r in Query(min_cut=60).apply(rs)] == ["Cheap indie"]
    assert Query(lowest=True).apply([R(cheap, None)]) == []                           # unknown history: not proven


def test_defaults_follow_the_profile_and_zero_lifts_them():
    c = config.cfg
    c.budget, c.min_discount = 5.0, 30
    r = R(item(1, "x", cut=25, price=999))
    assert Query().apply([r]) == []                    # $9.99 > profile budget and −25% < 30%
    assert Query(max_price=0, min_cut=0).apply([r]) == [r]


def test_ending_since_reviews_and_sort():
    now = time.time()

    def year(y):
        return int(time.mktime((y, 5, 1, 0, 0, 0, 0, 0, -1)))
    a = item(1, "A", cut=50, price=500, ends_at=int(now + 3600), release=year(2023), review_count=300)
    b = item(2, "B", cut=90, price=100, ends_at=int(now + 9 * 86400), release=year(2015), review_count=90000)
    rs = [R(a, score=90), R(b, score=40)]
    assert [r.item.name for r in Query(ending=1).apply(rs)] == ["A"]
    assert [r.item.name for r in Query(since=2020).apply(rs)] == ["A"]
    assert [r.item.name for r in Query(max_reviews=1000).apply(rs)] == ["A"]
    assert [r.item.name for r in Query(min_score=50).apply(rs)] == ["A"]
    assert [r.item.name for r in Query(sort="price").apply(rs)] == ["B", "A"]
    assert [r.item.name for r in Query(sort="cut").apply(rs)] == ["B", "A"]
    # default sort: equal deal value, so the better-reviewed game (90 000 reviews) goes first
    assert [r.item.name for r in Query(sort="score").apply(rs)] == ["B", "A"]


def test_tags_resolve_in_english_russian_and_by_prefix(tags):
    assert query.resolve_tag("indie") == "Indie"
    config.cfg.lang = "ru"
    assert query.resolve_tag("инди") == "Indie"
    assert query.resolve_tag("рогал") == "Roguelike"
    assert query.resolve_tags("rpg|стратегия") == "RPG|Strategy"
    with pytest.raises(QueryError):
        query.resolve_tag("zzzz-not-a-tag")


def test_flags_round_trip_through_a_macro(tags):
    q = query.parse("-x -b 2 -g indie,horror -G racing --lowest --min-rating 90 --ending 3 -s price")
    assert (q.tab, q.max_price, q.tags, q.no_tags, q.lowest, q.min_rating, q.ending, q.sort) == (
        "discover", 2.0, ["Indie", "Horror"], ["Racing"], True, 90, 3, "price")
    assert query.parse(q.to_args()) == q
    with pytest.raises(QueryError):
        query.parse("--no-such-flag")


def test_chips_read_like_a_sentence(tags):
    q = query.parse("-b 2 -g indie --lowest --min-rating 90")
    assert q.chips() == ["≤ $2.00", "★ record low", "indie", "≥ 90% positive"]


def test_macros_save_expand_combine_and_remove(tags):
    query.save_macro("cheap", "-b 2 -g indie --lowest", reserved={"dlc"})
    assert config.Settings.load().macros["cheap"] == "-b 2 -g indie --lowest"     # persisted in config.toml
    argv, used = query.expand(["cheap", "gems", "-d", "80"], {"dlc"}, {"-d"})
    assert used == ["cheap", "gems"] and argv[-2:] == ["-d", "80"] and "--lowest" in argv
    with pytest.raises(QueryError):
        query.save_macro("dlc", "-b 1", reserved={"dlc"})                      # can't shadow a command
    with pytest.raises(QueryError):
        query.save_macro("bad", "--nope", reserved=set())                      # validated before saving
    query.save_macro("gems", "-x --min-rating 99", reserved=set())             # yours beats the built-in
    assert query.all_macros()["gems"] == ("-x --min-rating 99", False)
    assert query.remove_macro("cheap") and query.remove_macro("gems")
    assert query.all_macros()["gems"][1] is True                               # built-in is back


def test_cli_macro_commands(tags, capsys):
    assert cli.main(["macro", "add", "cheap", "-b", "2", "-g", "indie", "--lowest"]) == 0
    assert "sift cheap" in capsys.readouterr().out
    assert cli.main(["macro"]) == 0
    out = capsys.readouterr().out
    assert "cheap" in out and "gems" in out and "record low" in out
    assert cli.main(["macro", "add", "info", "-b", "1"]) == 2               # a command name
    assert cli.main(["macro", "add", "nothing"]) == 2                       # no flags
    assert cli.main(["macro", "rm", "cheap"]) == 0
    assert cli.main(["macro", "rm", "gems"]) == 1                           # built-in
    capsys.readouterr()


def _capture(monkeypatch, tty: bool):
    seen = {}
    monkeypatch.setattr(cli, "ready", lambda quiet=False: True)
    monkeypatch.setattr(cli, "cmd_app", lambda args: seen.setdefault("app", args.query) and 0)
    monkeypatch.setattr(cli, "cmd_deals", lambda args: seen.setdefault("print", args.query) and 0)
    monkeypatch.setattr("sys.stdin.isatty", lambda: tty, raising=False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: tty, raising=False)
    return seen


def test_plain_sift_opens_the_app_with_flags_and_macros(tags, monkeypatch):
    query.save_macro("cheap", "-b 2 -g indie --lowest", reserved=set())
    seen = _capture(monkeypatch, tty=True)
    assert cli.main(["cheap", "-x", "-d", "70"]) == 0
    q = seen["app"]
    assert (q.tab, q.max_price, q.tags, q.lowest, q.min_cut, q.macros) == ("discover", 2.0, ["Indie"], True, 70,
                                                                          ["cheap"])
    query.remove_macro("cheap")


def test_piped_or_print_gives_a_table(tags, monkeypatch):
    seen = _capture(monkeypatch, tty=False)
    assert cli.main(["-g", "horror"]) == 0 and seen["print"].tags == ["Horror"]
    seen = _capture(monkeypatch, tty=True)
    assert cli.main(["--print", "lows"]) == 0 and seen["print"].lowest


def test_unknown_word_suggests_commands_and_macros(capsys):
    assert cli.main(["gemz"]) == 2
    assert "sift gems" in capsys.readouterr().out
    assert cli.main(["ui"]) == 2                                             # `sift ui` is gone: `sift` is the app
    capsys.readouterr()


def test_bad_tag_is_a_clear_error(tags, monkeypatch, capsys):
    _capture(monkeypatch, tty=True)
    assert cli.main(["-g", "qqqqqq"]) == 2
    assert "qqqqqq" in capsys.readouterr().out


def test_2y_low_rare_bundle_filters_and_deal_sorts(tags):
    a_it = item(1, "Rare 2Y Bundle", PUZZLE, cut=75, price=299)
    a_it.bundle_id = 555
    a_it.included_games = 3
    a_it.complete_the_set = True
    b_it = item(2, "Frequent ATL", RACING, cut=80, price=499)
    r_a = R(a_it, History(best_cut=90, low_2y_cut=75, covered_days=730, sales_2y=1, gap_days=240),
            score=70, deal_score=88, affinity=0.45)
    r_b = R(b_it, History(best_cut=80, low_2y_cut=80, covered_days=730, sales_2y=16, gap_days=35),
            score=82, deal_score=74, affinity=0.90)
    rs = [r_a, r_b]
    # 2Y low matches both (75 >= 75 and 80 >= 80), whereas ATL matches only b_it
    assert [r.item.name for r in Query(max_price=0, min_cut=0, lowest=True).apply(rs)] == ["Frequent ATL"]
    assert {r.item.name for r in Query(max_price=0, min_cut=0, low_2y=True).apply(rs)} == {
        "Rare 2Y Bundle", "Frequent ATL"}
    assert [r.item.name for r in Query(max_price=0, min_cut=0, rare=True).apply(rs)] == ["Rare 2Y Bundle"]
    assert [r.item.name for r in Query(max_price=0, min_cut=0, bundle=True).apply(rs)] == ["Rare 2Y Bundle"]
    # deal = most worthwhile first: the rare 2-year low is HOT, the frequent record only GREAT;
    # old names are aliases of it
    for name in ("deal", "rarity", "atl"):
        assert [r.item.name for r in Query(max_price=0, min_cut=0, sort=name).apply(rs)] == [
            "Rare 2Y Bundle", "Frequent ATL"]
    assert [r.item.name for r in Query(max_price=0, min_cut=0, sort="taste").apply(rs)] == [
        "Frequent ATL", "Rare 2Y Bundle"]
    # Flag round-trip for new flags
    q = query.parse("--2y-low --rare --bundle -s deal")
    assert q.low_2y and q.rare and q.bundle and q.sort == "deal"
    assert query.parse(q.to_args()) == q
    # Built-in macros include 2y, rare, bundles
    macros = query.all_macros()
    assert "2y" in macros and "rare" in macros and "bundles" in macros




def test_family_games_are_hidden_unless_asked_for(monkeypatch):
    from steamsift import config
    fam, mine = R(item(1, "Shared", cut=50)), R(item(2, "New", cut=50))
    fam.extras = {"family": "sam"}
    assert [r.item.name for r in Query().apply([fam, mine])] == ["New"]              # default: hidden
    assert {r.item.name for r in Query(family=True).apply([fam, mine])} == {"Shared", "New"}
    monkeypatch.setattr(config.cfg.profile.filters, "family", True)                   # sift config set family on
    assert len(Query().apply([fam, mine])) == 2 and Query(family=False).apply([fam, mine]) == [mine]
    q = query.parse("--family -d 30")
    assert q.family is True and "--family" in q.to_args() and query.parse("--no-family").family is False
