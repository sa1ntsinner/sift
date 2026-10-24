"""Regional correctness of store items (fixtures recorded from the live store)."""
import pytest

from steamsift import config, steam
from steamsift.engine import eligible
from steamsift.steam import LANG_AUDIO, LANG_SUBS, TYPE_GAME, get_items, split_family

RDR2, MAFIA2, RE4, PORTAL2, WITCHER3, ELDEN, SOUNDTRACK, CP2077 = (
    1174180, 1030830, 2050650, 620, 292030, 1245620, 2148100, 1091500)
ALL = [RDR2, MAFIA2, RE4, PORTAL2, WITCHER3, ELDEN, SOUNDTRACK, CP2077]


def use_country(cc):
    config.cfg.country = cc


@pytest.mark.parametrize("cc,blocked", [
    ("US", set()), ("TR", set()), ("KZ", set()), ("DE", set()), ("BR", set()), ("IN", set()),
    ("RU", {RDR2, MAFIA2, RE4, WITCHER3, CP2077}),      # publishers that left Russia
    ("SA", {MAFIA2}),                                   # content restrictions in the Gulf
])
def test_availability_per_region(steam_offline, cc, blocked):
    use_country(cc)
    items = get_items(ALL)
    assert set(items) == set(ALL), "every game keeps its metadata"
    assert {a for a, i in items.items() if not i.available} == blocked


def test_region_blocked_games_still_get_tags_for_taste(steam_offline):
    use_country("RU")
    rdr2 = get_items([RDR2])[RDR2]
    assert not rdr2.available and not rdr2.purchasable
    assert "Open World" in rdr2.tags and rdr2.review_count > 100_000
    assert steam_offline == ["RU", "US"], "metadata falls back to the neutral store once"


def test_prices_are_local(steam_offline):
    use_country("KZ")
    rdr2 = get_items([RDR2])[RDR2]
    assert rdr2.final_fmt.endswith("₸") and rdr2.final_cents > 100_000


def test_prices_are_cached_per_country(steam_offline):
    use_country("TR")
    tr = get_items([PORTAL2])[PORTAL2]
    use_country("KZ")
    kz = get_items([PORTAL2])[PORTAL2]
    assert tr.final_fmt.startswith("$") and kz.final_fmt.endswith("₸")


def test_family_sharing_flag_and_split(steam_offline):
    use_country("TR")
    items = get_items(ALL, with_price=False)
    assert not items[RDR2].family_shareable and items[ELDEN].family_shareable
    family = {RDR2: {"name": "RDR2", "owner": "sam"}, ELDEN: {"name": "ER", "owner": "sam"},
              999999: {"name": "delisted", "owner": "sam"}}
    shared, unshared = split_family(family, items)
    assert shared == {ELDEN, 999999} and unshared == {RDR2}


def test_languages_deck_and_type(steam_offline):
    use_country("US")
    items = get_items(ALL, with_price=False)
    ru_rdr2, ru_re4 = items[RDR2].languages["8"], items[RE4].languages["8"]
    assert ru_rdr2 & LANG_SUBS and not ru_rdr2 & LANG_AUDIO      # Russian subtitles, no voice-over
    assert ru_re4 & LANG_AUDIO
    assert items[ELDEN].deck == 3 and items[RDR2].deck == 2
    assert items[SOUNDTRACK].type != TYPE_GAME


def test_eligibility_respects_region_ownership_and_editions(steam_offline):
    use_country("RU")
    items = get_items(ALL)
    assert not eligible(items[RDR2], set(), set())                 # not sold in RU
    assert eligible(items[PORTAL2], set(), set())
    assert not eligible(items[PORTAL2], {PORTAL2}, set())          # owned / shared / hidden
    assert not eligible(items[PORTAL2], set(), {"portal 2"})       # another edition owned
    assert not eligible(items[SOUNDTRACK], set(), set())           # not a game


def test_store_lookup_prefers_games_and_neutral_relevance(monkeypatch, steam_offline):
    use_country("RU")
    regional = [(9001, "Dead Red Bennie")]                         # what the RU store suggests
    neutral = [(RDR2, "Red Dead Redemption 2"), (9002, "Red Dead Online"), (SOUNDTRACK, "Red Dead OST")]
    monkeypatch.setattr(steam, "_lookup", lambda term, cc: neutral if cc == "US" else regional)
    assert steam.store_lookup("red dead")[0][0] == RDR2
