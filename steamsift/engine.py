"""The deal-intelligence and recommendation service shared by the CLI, the TUI, notifications and the Telegram bot.

    ctx = Context.load()                 # library, family, hidden, taste profile, today's sale pool
    digest = build_digest(ctx, limit=12) # ranked wishlist deals + picks with history, hints, extras
    ctx.load_discovery_pool(); build_digest(ctx, discover=True).discover   # + new-for-you lanes
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

from . import calendar, config, discover as disc, itad, prefs, region
from .config import Filters
from .recommender import (Profile as TasteProfile, Rec, TagSpace, build_profile, calibrate, deal_value, diversify,
                          make_rec, wilson_lower)
from .steam import (LANG_AUDIO, LANG_SUBS, LANG_UI, TYPE_DLC, TYPE_GAME, Item, Library, get_items, load_library,
                    search_many, split_family, store_lookup, tag_names, third_party_accounts)

BASE_PAGES = [{"start": s, "count": 100} for s in range(0, 400, 100)]
# Discover: the best-reviewed games on sale, whatever they are (frontier genres are added per profile).
DISCOVER_PAGES = [{"start": s, "count": 100, "sort": "Reviews_DESC"} for s in range(0, 300, 100)]
DLC_PAGES = [{"start": s, "count": 100, "category": "21"} for s in range(0, 800, 100)]

# Steam ELanguage ids (as used in supported_languages)
ELANG = {"english": 0, "german": 1, "french": 2, "italian": 3, "koreana": 4, "spanish": 5, "schinese": 6,
         "tchinese": 7, "russian": 8, "thai": 9, "japanese": 10, "portuguese": 11, "polish": 12, "danish": 13,
         "dutch": 14, "finnish": 15, "norwegian": 16, "swedish": 17, "hungarian": 18, "czech": 19, "romanian": 20,
         "turkish": 21, "brazilian": 22, "bulgarian": 23, "greek": 24, "arabic": 25, "ukrainian": 26, "latam": 27,
         "vietnamese": 28, "indonesian": 29}
ADULT_DESCRIPTORS = {3, 4}   # Adult Only Sexual Content, Frequent Nudity or Sexual Content


def cfg() -> config.Runtime:
    return config.cfg


# --------------------------------------------------------------------------- filters

def passes_filters(item: Item, f: Filters, ui_steam_lang: str = "english") -> bool:
    """Hard preference filters for recommendations (the wishlist is your explicit choice and isn't filtered)."""
    if f.game_lang and item.languages:
        lid = str(ELANG.get(f.game_lang_name or ui_steam_lang, 0))
        bits = item.languages.get(lid, 0)
        need = LANG_AUDIO if f.game_lang == "audio" else (LANG_UI | LANG_SUBS)
        if not bits & need:
            return False
    if f.deck == "verified" and item.deck != 3:
        return False
    if f.deck == "playable" and item.deck not in (2, 3):
        return False
    if f.platforms and item.platforms and not set(f.platforms) & set(item.platforms):
        return False
    if not f.adult and ADULT_DESCRIPTORS & set(item.content):
        return False
    if f.early_access == "hide" and item.early_access:
        return False
    if item.vr_only and not f.vr_only:
        return False
    if f.exclude_tags and item.tags:
        top = {t for t, _ in sorted(item.tags.items(), key=lambda kv: -kv[1])[:10]}
        if top & set(f.exclude_tags):
            return False
    if item.review_count < f.min_reviews:
        return False
    if f.min_positive and (item.review_pct or 0) < f.min_positive:
        return False
    return True


def eligible(i: Item, excluded: set[int], owned_names: set[str]) -> bool:
    """A purchasable game you can't already play in any edition."""
    return (i.available and i.purchasable and i.type == TYPE_GAME and not i.is_free and i.final_cents > 0
            and i.appid not in excluded and prefs.normalize_title(i.name) not in owned_names)


# --------------------------------------------------------------------------- context

class Context:
    """Library, family sharing, hidden games and taste profile — built once per run."""

    with_family: bool | None = None   # None = the `family` setting; the app loads them always and filters live

    def __init__(self, extra_candidates: list[int] | None = None):
        self.lib: Library = load_library()
        self.hidden = prefs.load_hidden()
        self.seeds = list(cfg().profile.seeds)
        self.interest = prefs.interest()

        fam_meta = get_items(list(self.lib.family_games), with_price=False) if self.lib.family_games else {}
        self.family_shared, self.family_unshared = split_family(self.lib.family_games, fam_meta)

        played = [a for a, g in self.lib.my_games.items() if g.get("playtime_forever", 0) >= 3]
        if not self.lib.playtime_visible:
            played = list(self.lib.my_games)
        meta_ids = played + [w["appid"] for w in self.lib.wishlist] + list(self.hidden) + self.seeds + list(self.interest)
        self.meta = get_items(meta_ids, with_price=False)
        self.wish_items = get_items([w["appid"] for w in self.lib.wishlist], with_price=True)
        self.candidates: dict[int, Item] = get_items(extra_candidates, True) if extra_candidates else {}
        self.rebuild()

    @classmethod
    def load(cls, with_pool: bool = True) -> "Context":
        ctx = cls(search_many(BASE_PAGES) if with_pool else None)
        if with_pool:
            ctx.load_pool()
        return ctx

    def rebuild(self) -> None:
        corpus = [i.tags for i in {**self.meta, **self.candidates}.values() if i.tags]
        self.space = TagSpace.build(corpus)
        fallback = 2.0 if not self.lib.playtime_visible else None
        self.profile: TasteProfile = build_profile(self.lib, self.meta, self.space, self.hidden, fallback,
                                                   self.seeds, self.interest)

    def add_candidates(self, appids: list[int]) -> None:
        self.candidates.update(get_items(appids, with_price=True))
        self.rebuild()

    def load_pool(self) -> None:
        """Top sellers on sale + highest-rated specials + specials matching your most distinctive tags."""
        rev = {v: k for k, v in tag_names("english").items()}
        tag_ids = [rev[tg] for tg, _ in self.profile.top_tags(6) if tg in rev]
        targeted = [{"start": 0, "count": 100, "tag_ids": [tid]} for tid in tag_ids]
        targeted += [{"start": 0, "count": 100, "tag_ids": tag_ids[:2]}] if len(tag_ids) >= 2 else []
        self.add_candidates(search_many(DISCOVER_PAGES[:2] + targeted))

    def load_discovery_pool(self) -> None:
        """Acclaimed games on sale + top sellers of genres you barely play (a new handful every week)."""
        rev = {v: k for k, v in tag_names("english").items()}
        frontier = [{"start": 0, "count": 100, "tag_ids": [rev[g]]} for g in disc.frontier(self.profile) if g in rev]
        self.add_candidates(search_many(DISCOVER_PAGES + frontier))

    @property
    def filters(self) -> Filters:
        return cfg().profile.filters

    @property
    def show_family(self) -> bool:
        return self.filters.family if self.with_family is None else self.with_family

    @property
    def excluded(self) -> set[int]:
        """Yours, hidden by you, and (unless asked for) what your family already shares."""
        family = set() if self.show_family else self.family_shared
        return set(self.lib.my_games) | family | set(self.hidden)

    def owned_names(self) -> set[str]:
        names = [g["name"] for g in self.lib.my_games.values()]
        names += [self.lib.family_games[a]["name"] for a in self.family_shared]
        return {prefs.normalize_title(n) for n in names if n}

    def _bundle_info(self, item: Item) -> dict | None:
        if not item.is_bundle and not item.edition_kind:
            return None
        owned_ids = set(self.lib.my_games) | self.family_shared
        if item.bundle_appids:
            owned_in_set = len(set(item.bundle_appids) & owned_ids)
        elif item.complete_the_set and item.franchises:
            fset = set(item.franchises)
            owned_in_set = sum(
                1 for aid in self.lib.my_games
                if aid != item.appid and self.meta.get(aid) and (set(self.meta[aid].franchises) & fset)
            )
        else:
            owned_in_set = 0
        badge = item.bundle_badge(owned_in_set)
        if not badge:
            return None
        return {
            "bundle_id": item.bundle_id,
            "package_id": item.package_id,
            "option_name": item.option_name,
            "included_games": item.included_games,
            "bundle_discount": item.bundle_discount,
            "complete_the_set": item.complete_the_set,
            "owned_in_set": owned_in_set,
            "edition": item.edition_kind,
            "url": item.bundle_url,
            "badge": badge,
        }

    def rec(self, item: Item, is_wish: bool) -> Rec:
        r = make_rec(item, self.profile, self.space, is_wish, self.filters.explore)
        if item.appid in self.family_unshared:
            r.extras["unshared"] = self.lib.family_games[item.appid]["owner"]
        elif item.appid in self.family_shared:
            r.extras["family"] = self.lib.family_games[item.appid]["owner"]
        bnd = self._bundle_info(item)
        if bnd:
            r.extras["bundle"] = bnd
        return r


# --------------------------------------------------------------------------- digest

@dataclass
class Digest:
    wish: list[Rec]
    picks: list[Rec]
    unavailable: int
    scanned: int
    sale_now: calendar.Event | None = None
    sale_next: calendar.Event | None = None
    fests: list[calendar.Event] = field(default_factory=list)
    discover: list[Rec] = field(default_factory=list)      # new-for-you, ordered in genre lanes (Rec.lane)


def _in_budget(item: Item, budget: float | None) -> bool:
    return budget is None or item.price <= budget


def enrich(recs: list[Rec], ctx: Context, sale_next: calendar.Event | None = None,
           deep: list[Rec] | None = None) -> None:
    """Batch Steam lows for all recs; full logs and offers for at most 150 deep games."""
    if not recs:
        return
    ids = [r.item.appid for r in recs]
    deep_ids = ids if deep is None else list(dict.fromkeys(r.item.appid for r in deep))
    deep_ids = deep_ids[:150]
    hist = itad.history(ids, deep=deep_ids)
    bundles = itad.bundles(deep_ids[:40])         # one request per game: only the top of the lists
    accounts = third_party_accounts(deep_ids) if deep_ids else {}
    c = cfg()
    cheaper = itad.elsewhere(deep_ids, c.country) if deep_ids and itad.elsewhere_enabled(ctx.filters.elsewhere,
                                                                                            c.country) else {}
    targets = prefs.targets()
    for r in recs:
        a = r.item.appid
        r.hist = hist.get(a)
        r.extras.pop("bundle3p", None)
        if a in bundles:
            r.extras["bundle3p"] = bundles[a]
        r.extras["sale_next"] = sale_next
        if accounts.get(a):
            r.extras["account"] = accounts[a]
        if a in cheaper:
            r.extras["elsewhere"] = cheaper[a]
        tgt = targets.get(a)
        if tgt is not None:
            hit = (r.item.final_cents <= tgt["price_cents"]) if tgt["price_cents"] is not None else \
                bool(r.hist and r.hist.is_atl(r.item.cut))
            r.extras["target"] = {"price_cents": tgt["price_cents"], "hit": hit}
            if hit:
                r.intent = max(r.intent, 1.0)
        at_low = bool(r.hist and r.hist.is_atl(r.item.cut))
        if sale_next and not at_low:
            r.extras["wait"] = sale_next
        r.rescore()


def build_digest(ctx: Context, limit: int = 12, min_discount: int | None = None, budget: float | None = None,
                 show_wish: bool = True, show_picks: bool = True, today: dt.date | None = None,
                 discover: bool = False, history_all: bool = False) -> Digest:
    """Ranked wishlist deals and picks (+ discover lanes). `limit` sizes the fully enriched head;
    `history_all` also attaches price history to everything else (the app filters on record lows)."""
    c = cfg()
    min_discount = c.min_discount if min_discount is None else min_discount
    budget = c.budget if budget is None else (budget or None)
    excluded, owned_names, wish_ids = ctx.excluded, ctx.owned_names(), ctx.lib.wishlist_ids
    f = ctx.filters

    unavailable = sum(1 for i in ctx.wish_items.values() if not i.available)
    all_wish = [ctx.rec(i, True) for i in ctx.wish_items.values()
                if i.available and i.purchasable and i.cut > 0 and i.appid not in excluded]
    all_picks = [ctx.rec(i, False) for i in ctx.candidates.values()
                 if i.cut > 0 and i.appid not in wish_ids and eligible(i, excluded, owned_names)
                 and passes_filters(i, f, c.steam_lang)]
    calibrate(all_wish + all_picks)        # one scale for every view and filter

    def keep(r: Rec) -> bool:
        return r.item.cut >= min_discount and _in_budget(r.item, budget)

    wish = sorted((r for r in all_wish if keep(r)), key=lambda r: -r.score)
    picks = [r for r in all_picks if keep(r)]
    finds = disc.candidates(picks, ctx.profile, ctx.space, ctx.interest, today) if discover else []
    if not show_wish:
        picks += wish
    picks = diversify(sorted(picks, key=lambda r: -r.score))
    finds.sort(key=lambda r: -r.score)

    evs = calendar.events()
    sale_now, sale_next = calendar.current_sale(today, evs=evs), calendar.next_sale(today, evs=evs)
    head, find_head = picks[: limit * 3], finds[: limit * 3]
    deep = (wish[: limit * 2] + head + find_head)[:150]
    deep_objects = {id(r) for r in deep}
    rest = [r for r in wish + picks + finds if id(r) not in deep_objects]
    enrich(deep + rest, ctx, sale_next, deep=deep)
    if not f.third_party:
        head = [r for r in head if "account" not in r.extras]
        find_head = [r for r in find_head if "account" not in r.extras]
    picks = diversify(sorted(head, key=lambda r: -r.score)) + sorted(picks[limit * 3:], key=lambda r: -r.score)
    wish.sort(key=lambda r: -r.score)
    finds = disc.arrange(find_head + finds[limit * 3:])
    if finds:
        disc.remember(finds, today)
    fests = calendar.fests_for([t for t, _ in ctx.profile.top_tags(5)], today, evs=evs)
    return Digest(wish if show_wish else [], picks if show_picks else [], unavailable, len(ctx.candidates),
                  sale_now, sale_next, fests, finds)


# --------------------------------------------------------------------------- DLC

@dataclass
class DlcRow:
    item: Item
    owner: str
    owner_kind: str          # "you" | "unplayed" | "family"
    hours: float
    base_name: str
    engage: float
    quality: float
    hist: itad.History | None = None

    @property
    def is_atl(self) -> bool:
        return bool(self.hist and self.hist.is_atl(self.item.cut))

    @property
    def is_2y_low(self) -> bool:
        return bool(self.hist and self.hist.is_2y_low(self.item.cut))

    @property
    def deal_score(self) -> float:
        d = deal_value(self.item.cut, self.hist, self.item)
        return round(100 * (0.60 * d + 0.25 * self.quality + 0.15 * self.engage), 1)

    @property
    def score(self) -> float:
        return 0.45 * self.engage + 0.35 * deal_value(self.item.cut, self.hist, self.item) + 0.20 * self.quality


def dlc_rows(limit: int = 12, min_discount: int | None = None, budget: float | None = None) -> tuple[list[DlcRow], int]:
    c = cfg()
    min_discount = c.min_discount if min_discount is None else min_discount
    budget = c.budget if budget is None else (budget or None)
    lib = load_library()
    hidden = prefs.load_hidden()
    fam_meta = get_items(list(lib.family_games), with_price=False) if lib.family_games else {}
    fam_shared = split_family(lib.family_games, fam_meta)[0]
    items = get_items([a for a in search_many(DLC_PAGES) if a not in hidden], with_price=True)
    rows: list[DlcRow] = []
    for it in items.values():
        parent = it.parent_appid
        if (it.type != TYPE_DLC or not parent or not it.available or not it.purchasable
                or it.cut < min_discount or not _in_budget(it, budget)):
            continue
        if parent in lib.my_games:
            hours = lib.my_games[parent].get("playtime_forever", 0) / 60
            kind = "you" if hours >= 1 else "unplayed"
            rows.append(DlcRow(it, lib.my_games[parent]["name"], kind, hours, lib.my_games[parent]["name"],
                               min(1.0, math.log1p(hours) / math.log1p(80)), 0))
        elif parent in fam_shared:
            fg = lib.family_games[parent]
            rows.append(DlcRow(it, fg["owner"], "family", 0, fg["name"], 0.25, 0))
        else:
            continue
        wl = wilson_lower(it.review_pct, it.review_count)
        rows[-1].quality = 0.4 if wl is None else max(0.0, min(1.0, (wl - 0.45) / 0.5))
    rows.sort(key=lambda r: -r.score)
    hist = itad.history([r.item.appid for r in rows[: limit * 2]])
    for r in rows:
        r.hist = hist.get(r.item.appid)
    rows.sort(key=lambda r: -r.score)
    return rows, len(items)


# --------------------------------------------------------------------------- single game

def resolve_game(query: str) -> int | None:
    query = query.strip()
    if query.isdigit():
        return int(query)
    hits = store_lookup(query)
    return hits[0][0] if hits else None


def game_rec(ctx: Context, appid: int) -> Rec | None:
    """A fully enriched Rec for one game, calibrated on the same pool as the main list."""
    item = get_items([appid], with_price=True).get(appid)
    if not item:
        return None
    wish = ctx.lib.wishlist_ids
    rec = ctx.rec(item, appid in wish)
    excluded, names = ctx.excluded, ctx.owned_names()
    pool = [ctx.rec(i, i.appid in wish) for i in {**ctx.candidates, **ctx.wish_items}.values()
            if i.appid != appid and i.available and (i.appid in wish or eligible(i, excluded, names))]
    calibrate(pool + [rec])
    evs = calendar.events()
    enrich([rec], ctx, calendar.next_sale(evs=evs))
    return rec


def status_of(ctx: Context, appid: int) -> tuple[str, dict]:
    """(status key, params) for i18n: owned / family / family_unshared / hidden / wishlist / ''."""
    lib = ctx.lib
    if appid in lib.my_games:
        return "st_owned", {"h": f"{lib.my_games[appid].get('playtime_forever', 0) / 60:.0f}"}
    if appid in ctx.family_shared:
        return "st_family", {"owner": lib.family_games[appid]["owner"]}
    if appid in ctx.family_unshared:
        return "st_family_unshared", {"owner": lib.family_games[appid]["owner"]}
    if appid in ctx.hidden:
        return "st_hidden", {}
    if appid in lib.wishlist_ids:
        return "st_wishlist", {}
    return "", {}


def country_name() -> str:
    return region.name(cfg().country, cfg().lang)
