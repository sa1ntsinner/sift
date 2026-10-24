"""Steam data layer: library, family, wishlist, batched store items, bundles, search."""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
from dataclasses import dataclass, field

from . import config, localsteam
from .db import DAY, HOUR, Cache, db
from .i18n import t
from .net import request_json

API = "https://api.steampowered.com"
STORE = "https://store.steampowered.com"

TYPE_GAME, TYPE_DLC = 0, 4
CAT_FAMILY_SHARING = 62
CAT_VR_ONLY = 54
ASSET_CDN = "https://shared.fastly.steamstatic.com/store_item_assets/"
META_COUNTRY = "US"          # neutral store used to fetch tags for games hidden in the user's region

# Language bits in Item.languages
LANG_UI, LANG_SUBS, LANG_AUDIO = 1, 2, 4

_library_cache = Cache("library", volatile=True)
_meta_cache = Cache("items_meta_v4")                 # tags, reviews, franchise, platforms… (slow-changing)
_price_cache = Cache("items_price_v2", volatile=True)  # keyed "<country>:<appid>"
_search_cache = Cache("search", volatile=True)
_tag_cache = Cache("tag_names")
_lookup_cache = Cache("store_lookup")

META_TTL = 10 * DAY
PRICE_TTL = 1 * HOUR
LIBRARY_TTL = 1 * HOUR
SEARCH_TTL = 45 * 60

_EDITION_RE = re.compile(
    r"\b(deluxe|ultimate|complete|definitive|game of the year|goty|collector'?s|gold|anniversary|premium)\b",
    re.IGNORECASE,
)


def _cfg():
    return config.cfg


# --------------------------------------------------------------------------- models

@dataclass
class Item:
    appid: int
    name: str
    type: int = TYPE_GAME
    tags: dict[str, float] = field(default_factory=dict)  # English tag name -> community weight
    review_pct: int | None = None
    review_count: int = 0
    review_label: str = ""
    franchises: list[str] = field(default_factory=list)
    developers: list[str] = field(default_factory=list)
    release: int = 0
    parent_appid: int | None = None
    is_free: bool = False
    family_shareable: bool = True
    deck: int = 0                                   # 0 unknown, 1 unsupported, 2 playable, 3 verified
    platforms: list[str] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)  # Steam ELanguage id -> LANG_* bits
    content: list[int] = field(default_factory=list)          # content descriptor ids (3/4 = sexual content)
    vr_only: bool = False
    image: str = ""                                 # header image (460x215), exact CDN path

    # regional price & bundle state
    available: bool = True                          # listed in the user's store region (not region-blocked)
    purchasable: bool = True                        # has a price now (False for unreleased / delisted)
    cut: int = 0
    final_cents: int = 0
    orig_cents: int = 0
    final_fmt: str = ""
    orig_fmt: str = ""
    ends_at: int = 0
    package_id: int | None = None
    bundle_id: int | None = None
    option_name: str = ""
    included_games: int = 1
    bundle_discount: int = 0
    complete_the_set: bool = False
    bundle_appids: list[int] = field(default_factory=list)

    @property
    def cover(self) -> str:
        return self.image or f"{ASSET_CDN}steam/apps/{self.appid}/header.jpg"

    @property
    def url(self) -> str:
        return f"{STORE}/app/{self.appid}/"

    @property
    def bundle_url(self) -> str:
        if self.bundle_id:
            return f"{STORE}/bundle/{self.bundle_id}/"
        if self.package_id and self.included_games > 1:
            return f"{STORE}/sub/{self.package_id}/"
        return self.url

    @property
    def itad_url(self) -> str:
        return f"https://isthereanydeal.com/steam/app/{self.appid}/"

    @property
    def price(self) -> float:
        return self.final_cents / 100.0

    @property
    def early_access(self) -> bool:
        return "Early Access" in self.tags

    @property
    def is_bundle(self) -> bool:
        return bool(self.bundle_id or self.bundle_discount > 0 or self.included_games > 1)

    @property
    def edition_kind(self) -> str:
        for text in (self.option_name, self.name):
            if text:
                m = _EDITION_RE.search(text)
                if m:
                    raw = m.group(1).lower()
                    return "goty" if "year" in raw else raw
        return ""

    def bundle_badge(self, owned_in_set: int = 0) -> str:
        """Human-readable localized summary of bundle / Complete-the-Set / edition value."""
        if not self.is_bundle and not self.edition_kind:
            return ""
        parts = []
        if self.complete_the_set and (self.bundle_id or self.bundle_discount > 0 or owned_in_set > 0):
            if self.bundle_discount > 0:
                parts.append(t("bnd_cts_pct", pct=self.bundle_discount))
            else:
                parts.append(t("bnd_cts"))
            if owned_in_set > 0:
                parts.append(t("bnd_owned_n", n=owned_in_set))
        elif self.is_bundle:
            if self.included_games > 1:
                parts.append(t("bnd_games_n", n=self.included_games))
            elif self.bundle_discount > 0:
                parts.append(t("bnd_extra_pct", pct=self.bundle_discount))
            else:
                parts.append(t("bnd_package"))
        if self.edition_kind and not parts:
            parts.append(t("bnd_edition", ed=self.edition_kind.upper() if self.edition_kind == "goty"
                           else self.edition_kind.capitalize()))
        return " · ".join(parts)


@dataclass
class Library:
    user_name: str
    steam_id: str
    my_games: dict[int, dict]
    family_name: str
    family_source: str                     # "client" | "manual" | ""
    family_members: list[dict]
    family_games: dict[int, dict]          # appid -> {name, owner}
    wishlist: list[dict]                   # [{appid, priority, date_added}]
    games_visible: bool = True             # False when "Game details" are private
    playtime_visible: bool = True          # False when playtime is hidden but games are listed

    @property
    def wishlist_ids(self) -> set[int]:
        return {w["appid"] for w in self.wishlist}


def split_family(family_games: dict[int, dict], meta: dict[int, "Item"]) -> tuple[set[int], set[int]]:
    """(shareable, not shareable). Steam Families only share games whose publisher enables
    category 62 "Family Sharing" (RDR2, CS2 … don't). Unknown/delisted games count as shared."""
    shared = {a for a in family_games if a not in meta or meta[a].family_shareable}
    return shared, set(family_games) - shared


# --------------------------------------------------------------------------- Web API

def _api(path: str, need_key: bool = True, **params) -> dict:
    key = _cfg().steam_api_key
    if key:
        params["key"] = key
    elif need_key:
        return {}
    data = request_json(f"{API}/{path}", params=params)
    return (data or {}).get("response", {}) if isinstance(data, dict) else {}


def get_owned_games(steamid: str) -> dict[int, dict]:
    cached = _library_cache.get(f"owned:{steamid}", LIBRARY_TTL)
    if cached is not None:
        return {int(k): v for k, v in cached.items()}
    resp = _api("IPlayerService/GetOwnedGames/v1/", steamid=steamid, include_appinfo=1,
                include_played_free_games=1)
    games = {
        g["appid"]: {
            "appid": g["appid"],
            "name": g.get("name", f"App {g['appid']}"),
            "playtime_forever": g.get("playtime_forever", 0),
            "playtime_2weeks": g.get("playtime_2weeks", 0),
            "rtime_last_played": g.get("rtime_last_played", 0),
        }
        for g in resp.get("games", [])
    }
    if games:  # never cache an empty answer (private profile / API hiccup)
        _library_cache.set(f"owned:{steamid}", games)
    return games


def get_wishlist(steamid: str) -> list[dict]:
    cached = _library_cache.get(f"wishlist:{steamid}", LIBRARY_TTL)
    if cached is not None:
        return cached
    items = _api("IWishlistService/GetWishlist/v1/", need_key=False, steamid=steamid).get("items", [])
    out = [{"appid": i["appid"], "priority": i.get("priority", 0), "date_added": i.get("date_added", 0)}
           for i in items]
    if out:
        _library_cache.set(f"wishlist:{steamid}", out)
    return out


def get_player_summaries(steam_ids: list[str]) -> dict[str, dict]:
    key = "summaries:" + ",".join(sorted(steam_ids))
    cached = _library_cache.get(key, 24 * HOUR)
    if cached is not None:
        return cached
    players = _api("ISteamUser/GetPlayerSummaries/v2/", steamids=",".join(steam_ids)).get("players", [])
    out = {p["steamid"]: {"name": p.get("personaname", ""), "visibility": p.get("communityvisibilitystate", 1),
                          "avatar": p.get("avatarfull", ""), "country": p.get("loccountrycode", "")}
           for p in players}
    if out:
        _library_cache.set(key, out)
    return out


def load_library() -> Library:
    c = _cfg()
    me = c.steam_id
    if c.family:
        family_ids, family_name, source = list(c.family), "Steam Family", "manual"
    else:
        fam = localsteam.family_from_client(me)
        family_ids, family_name = fam.get("member_steam_ids", []), fam.get("name", "Steam Family")
        source = "client" if fam else ""
    all_ids = list(dict.fromkeys([me, *family_ids]))

    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        f_sum = pool.submit(get_player_summaries, all_ids)
        f_wish = pool.submit(get_wishlist, me)
        f_owned = {sid: pool.submit(get_owned_games, sid) for sid in all_ids}
        summaries = f_sum.result()
        wishlist = f_wish.result()
        owned = {sid: f.result() for sid, f in f_owned.items()}

    my_games = owned.get(me, {})
    family_games: dict[int, dict] = {}
    members = []
    if len(all_ids) > 1:
        for sid in all_ids:
            is_me = sid == me
            name = summaries.get(sid, {}).get("name") or f"Member {sid[-4:]}"
            games = owned.get(sid, {})
            members.append({"steamid": sid, "name": name, "is_me": is_me, "games_count": len(games)})
            if is_me:
                continue
            for aid, g in games.items():
                if aid not in my_games and aid not in family_games:
                    family_games[aid] = {"appid": aid, "name": g["name"], "owner": name}

    return Library(
        user_name=summaries.get(me, {}).get("name") or "Steam User",
        steam_id=me,
        my_games=my_games,
        family_name=family_name,
        family_source=source,
        family_members=members,
        family_games=family_games,
        wishlist=wishlist,
        games_visible=bool(my_games),
        playtime_visible=any(g.get("playtime_forever") for g in my_games.values()),
    )


# --------------------------------------------------------------------------- tags

def tag_names(lang: str = "english") -> dict[int, str]:
    cached = _tag_cache.get(lang, 30 * DAY)
    if cached:
        return {int(k): v for k, v in cached.items()}
    tags: dict[int, str] = {}
    if _cfg().steam_api_key:
        data = request_json(f"{API}/IStoreService/GetTagList/v1/",
                            params={"language": lang, "key": _cfg().steam_api_key})
        for tg in (data or {}).get("response", {}).get("tags", []):
            tags[int(tg["tagid"])] = tg["name"]
    if not tags:
        data = request_json(f"{STORE}/tagdata/populartags/{lang}") or []
        tags = {int(tg["tagid"]): tg["name"] for tg in data} if isinstance(data, list) else {}
    if tags:
        _tag_cache.set(lang, tags)
    return tags


_local_tags: dict[str, str] | None = None


def local_tag(name_en: str) -> str:
    """Translate an English tag name into the UI language (Steam's own translations)."""
    global _local_tags
    lang = _cfg().steam_lang
    if lang == "english":
        return name_en
    if _local_tags is None:
        en, loc = tag_names("english"), tag_names(lang)
        _local_tags = {en[i]: loc[i] for i in en if i in loc}
    return _local_tags.get(name_en, name_en)


# --------------------------------------------------------------------------- store items

def _asset(assets: dict, key: str) -> str:
    fmt, name = assets.get("asset_url_format"), assets.get(key)
    return f"{ASSET_CDN}{fmt.replace('${FILENAME}', name)}" if fmt and name else ""


def _parse_item(raw: dict, names: dict[int, str]) -> tuple[dict | None, dict]:
    """(meta or None, regional price record)."""
    if raw.get("success") != 1 or not raw.get("visible", True):
        return None, {"available": False, "purchasable": False}
    reviews = (raw.get("reviews") or {}).get("summary_filtered") or {}
    basic = raw.get("basic_info") or {}
    cats = raw.get("categories") or {}
    plat = raw.get("platforms") or {}
    langs = {}
    for lang in raw.get("supported_languages") or []:
        if not lang.get("supported"):
            continue
        bits = LANG_UI | (LANG_SUBS if lang.get("subtitles") else 0) | (LANG_AUDIO if lang.get("full_audio") else 0)
        langs[str(lang.get("elanguage"))] = bits
    meta = {
        "appid": raw.get("appid") or raw.get("id"),
        "name": raw.get("name", ""),
        "type": raw.get("type", TYPE_GAME),
        "tags": {names[t["tagid"]]: t.get("weight", 1) for t in raw.get("tags", []) if t.get("tagid") in names},
        "review_pct": reviews.get("percent_positive"),
        "review_count": reviews.get("review_count", 0),
        "review_label": reviews.get("review_score_label", ""),
        "franchises": [f["name"] for f in basic.get("franchises", []) if f.get("name")],
        "developers": [d["name"] for d in basic.get("developers", []) if d.get("name")],
        "release": (raw.get("release") or {}).get("steam_release_date", 0),
        "parent_appid": (raw.get("related_items") or {}).get("parent_appid"),
        "is_free": bool(raw.get("is_free")),
        "family_shareable": CAT_FAMILY_SHARING in (cats.get("feature_categoryids") or []),
        "deck": plat.get("steam_deck_compat_category", 0) or 0,
        "platforms": [p for p, k in (("windows", "windows"), ("mac", "mac"), ("linux", "steamos_linux"))
                      if plat.get(k)],
        "languages": langs,
        "content": raw.get("content_descriptorids") or [],
        "vr_only": CAT_VR_ONLY in [c for ids in cats.values() if isinstance(ids, list) for c in ids],
        "image": _asset(raw.get("assets") or {}, "header"),
    }
    opt = raw.get("best_purchase_option") or {}
    ends = [d.get("discount_end_date", 0) for d in opt.get("active_discounts", []) if d.get("discount_end_date")]
    pkg_id = opt.get("packageid")
    bnd_id = opt.get("bundleid")
    opt_name = opt.get("purchase_option_name", "") or ""
    inc_games = int(opt.get("included_game_count", 1) or 1)
    bnd_disc = int(opt.get("bundle_discount_pct", 0) or 0)
    must_set = bool(opt.get("must_purchase_as_set", False))

    # Also check secondary purchase_options if a bundle is listed alongside the base option
    for alt in raw.get("purchase_options") or []:
        if alt.get("bundleid") or int(alt.get("bundle_discount_pct", 0) or 0) > 0:
            bnd_id = bnd_id or alt.get("bundleid")
            bnd_disc = max(bnd_disc, int(alt.get("bundle_discount_pct", 0) or 0))
            inc_games = max(inc_games, int(alt.get("included_game_count", 1) or 1))
            if not opt_name and alt.get("purchase_option_name"):
                opt_name = alt["purchase_option_name"]
            if not alt.get("must_purchase_as_set", False):
                must_set = False

    cts = bool(not must_set and (bnd_id or bnd_disc > 0 or inc_games > 1))
    price = {
        "available": True,
        "purchasable": bool(opt) or meta["is_free"],
        "cut": opt.get("discount_pct", 0) or 0,
        "final_cents": int(opt.get("final_price_in_cents", 0) or 0),
        "orig_cents": int(opt.get("original_price_in_cents", 0) or opt.get("final_price_in_cents", 0) or 0),
        "final_fmt": opt.get("formatted_final_price", ""),
        "orig_fmt": opt.get("formatted_original_price", "") or opt.get("formatted_final_price", ""),
        "ends_at": min(ends) if ends else 0,
        "package_id": int(pkg_id) if pkg_id is not None else None,
        "bundle_id": int(bnd_id) if bnd_id is not None else None,
        "option_name": opt_name,
        "included_games": inc_games,
        "bundle_discount": bnd_disc,
        "complete_the_set": cts,
    }
    return meta, price


def _fetch_batch(appids: list[int], country: str, names: dict[int, str]) -> list[tuple[int, dict | None, dict]]:
    payload = {
        "ids": [{"appid": a} for a in appids],
        "context": {"language": "english", "country_code": country, "steam_realm": 1},
        "data_request": {
            "include_basic_info": True, "include_tag_count": 20, "include_reviews": True,
            "include_release": True, "include_related_items": True, "include_platforms": True,
            "include_supported_languages": True, "include_assets": True,
        },
    }
    data = request_json(f"{API}/IStoreBrowseService/GetItems/v1",
                        params={"input_json": json.dumps(payload, separators=(",", ":"))})
    out = []
    for raw in (data or {}).get("response", {}).get("store_items", []):
        aid = raw.get("appid") or raw.get("id")
        if aid:
            meta, price = _parse_item(raw, names)
            out.append((int(aid), meta, price))
    return out


def _run_batches(appids: list[int], country: str) -> list[tuple[int, dict | None, dict]]:
    names = tag_names("english")
    batches = [appids[i: i + 100] for i in range(0, len(appids), 100)]
    results = []
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        for r in pool.map(lambda b: _fetch_batch(b, country, names), batches):
            results.extend(r)
    return results


def get_items(appids, with_price: bool = True, country: str | None = None) -> dict[int, Item]:
    """Store items for the user's region, in batches of 100, reusing cached metadata and prices.

    Games hidden in the region (e.g. many publishers in RU/BY) still get tags via a
    neutral store so they keep counting for the taste profile; they're marked unavailable.
    """
    country = (country or _cfg().country or META_COUNTRY).upper()
    appids = list(dict.fromkeys(int(a) for a in appids))
    pkey = lambda a: f"{country}:{a}"  # noqa: E731

    todo = [a for a in appids
            if _meta_cache.get(a, META_TTL) is None or (with_price and _price_cache.get(pkey(a), PRICE_TTL) is None)]
    if todo:
        for aid, meta, price in _run_batches(todo, country):
            if meta or country == META_COUNTRY:
                _meta_cache.set(aid, meta or {})
            _price_cache.set(pkey(aid), price)
            if price.get("purchasable") and price.get("final_cents"):
                db().record_price(aid, country, price["final_cents"], price["orig_cents"], price["cut"])

    no_meta = [a for a in appids if _meta_cache.get(a) is None]
    if no_meta and country != META_COUNTRY:
        for aid, meta, _ in _run_batches(no_meta, META_COUNTRY):
            _meta_cache.set(aid, meta or {})

    items: dict[int, Item] = {}
    for aid in appids:
        meta = _meta_cache.get(aid)
        if not meta:
            continue
        fields = dict(meta)
        if with_price:
            price = _price_cache.get(pkey(aid)) or {"available": False, "purchasable": False}
            fields.update(price)
        valid_fields = {k: v for k, v in fields.items() if k in Item.__dataclass_fields__}
        items[aid] = Item(**valid_fields)
    return items


_appdetails_cache = Cache("third_party")


def third_party_accounts(appids: list[int]) -> dict[int, str]:
    """appid -> notice like "EA Account" for games that need a non-Steam account (cached 30 days).

    Only `appdetails` exposes this, one request per game, so callers pass a short list."""
    out, todo = {}, []
    for a in appids:
        cached = _appdetails_cache.get(a, 30 * DAY)
        if cached is None:
            todo.append(a)
        else:
            out[a] = cached

    def fetch(a: int) -> tuple[int, str]:
        data = request_json(f"{STORE}/api/appdetails",
                            params={"appids": a, "cc": _cfg().country or META_COUNTRY, "l": "english"})
        d = ((data or {}).get(str(a)) or {}).get("data") or {} if isinstance(data, dict) else {}
        return a, (d.get("ext_user_account_notice") or "").split("(")[0].strip()

    if todo:
        with cf.ThreadPoolExecutor(max_workers=6) as pool:
            for a, notice in pool.map(fetch, todo):
                _appdetails_cache.set(a, notice)
                out[a] = notice
    return out


# --------------------------------------------------------------------------- search

_APPID_RE = re.compile(r'data-ds-appid="(\d+)"')


def search_specials(start: int = 0, count: int = 100, category: str = "998",
                    tag_ids: list[int] | None = None, sort: str = "") -> list[int]:
    """Discounted apps in the user's store (category 998 = games, 21 = DLC): top sellers,
    or `sort="Reviews_DESC"` for the best-reviewed ones."""
    country = _cfg().country or META_COUNTRY
    key = f"{country}:{category}:{start}:{count}:{','.join(map(str, tag_ids or []))}"
    key += f":{sort}" if sort else ""
    cached = _search_cache.get(key, SEARCH_TTL)
    if cached is not None:
        return cached
    params = {
        "query": "", "start": start, "count": count, "specials": 1, "infinite": 1,
        "cc": country, "l": "english", "filter": "topsellers", "category1": category,
    }
    if sort:
        params.pop("filter")
        params["sort_by"] = sort
    if tag_ids:
        params["tags"] = ",".join(map(str, tag_ids))
    data = request_json(f"{STORE}/search/results/", params=params, remote_fallback=True)
    html = (data or {}).get("results_html", "") if isinstance(data, dict) else ""
    ids = list(dict.fromkeys(int(m) for m in _APPID_RE.findall(html)))
    if ids:
        _search_cache.set(key, ids)
    return ids


def search_many(queries: list[dict]) -> list[int]:
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda q: search_specials(**q), queries))
    return list(dict.fromkeys(a for r in results for a in r))


def _lookup(term: str, country: str) -> list[tuple[int, str]]:
    key = f"{country}:{term.lower().strip()}"
    cached = _lookup_cache.get(key, 30 * DAY)
    if cached is not None:
        return [tuple(x) for x in cached]
    data = request_json(f"{STORE}/api/storesearch/",
                        params={"term": term, "cc": country, "l": "english"}, remote_fallback=True)
    res = [(int(i["id"]), i["name"]) for i in (data or {}).get("items", []) if i.get("type") == "app"]
    if res:
        _lookup_cache.set(key, res)
    return res


def store_lookup(term: str) -> list[tuple[int, str]]:
    """Resolve free text to Steam apps, best match first.

    The regional store hides blocked games (RDR2 in RU returns "Dead Red Bennie"), so the
    neutral store is searched too and results are ranked by how well the title matches.
    """
    import difflib

    from .prefs import normalize_title

    country = _cfg().country or META_COUNTRY
    neutral = _lookup(term, META_COUNTRY) if country != META_COUNTRY else []
    hits = list(dict.fromkeys(_lookup(term, country) + neutral))
    order = {h[0]: i for i, h in enumerate(neutral or hits)}   # Steam's relevance/popularity order
    want = normalize_title(term)

    def rank(hit: tuple[int, str]) -> float:
        name = normalize_title(hit[1])
        score = 0.4 * difflib.SequenceMatcher(None, want, name).ratio()
        if name == want:
            score += 1.0
        elif name.startswith(want) or all(w in name.split() for w in want.split()):
            score += 0.5
        score += 0.6 * (1 - order.get(hit[0], len(order)) / max(1, len(order)))
        return score

    ranked = sorted(hits, key=rank, reverse=True)[:8]
    types = {a: i.type for a, i in get_items([a for a, _ in ranked], with_price=False).items()}
    return sorted(ranked, key=lambda h: types.get(h[0], TYPE_GAME) != TYPE_GAME)   # games before DLC/soundtracks
