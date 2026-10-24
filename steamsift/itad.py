"""Steam price-change history and authorised third-party offers from ITAD."""
from __future__ import annotations

import datetime as dt
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from statistics import median

from . import config
from .db import DAY, HOUR, Cache, price_history, stale_ok
from .net import request_json

BASE = "https://api.isthereanydeal.com"
STEAM_SHOP = 61
_id_cache = Cache("itad_ids")
_hist_cache = Cache("itad_history_v3", volatile=True)
_log_cache = Cache("itad_log_v1")
_prices_cache = Cache("itad_steam_low_v1", volatile=True)
_bundle_cache = Cache("itad_bundles_v1", volatile=True)


@dataclass
class History:
    best_cut: int = 0
    low_1y_cut: int = 0
    low_2y_cut: int = 0
    sales_2y: int = 0
    gap_days: int = 0
    since_last_days: int = 0
    typical_cut: int = 0
    raised_days: int = -1
    covered_days: int = 0
    points: list[tuple[str, int]] = field(default_factory=list)
    regular_cents: int = 0      # current US base price (latest in the log, or ITAD's current deal)
    low_cents: int = 0          # lowest US price ever paid (log or ITAD storeLow)
    low_2y_cents: int = 0       # lowest US price in the last 730 days

    # A base price can move: $10 at −50% ($5) beats $15 at −60% ($6). With US prices known we compare
    # what you pay; without them we fall back to the discount percentages.

    def now_cents(self, cut: int) -> int:
        return round(self.regular_cents * (100 - cut) / 100) if self.regular_cents else 0

    def cheaper_pct(self, cut: int, two_years: bool = False) -> int:
        """How much cheaper (in %) the game has been than it is at `cut` today; 0 = never cheaper."""
        low = self.low_2y_cents if two_years else self.low_cents
        now = self.now_cents(cut)
        if low and now:
            return max(0, round(100 * (1 - low / now)))
        best = self.low_2y_cut if two_years else self.best_cut
        if best <= 0 or cut >= 100:
            return 0
        return max(0, round(100 * (1 - (100 - best) / (100 - cut))))

    def _known(self, two_years: bool = False) -> bool:
        if two_years:
            return bool(self.low_2y_cents and self.regular_cents) or self.low_2y_cut > 0
        return bool(self.low_cents and self.regular_cents) or self.best_cut > 0

    def is_atl(self, cut: int) -> bool:
        return cut > 0 and self._known() and self.cheaper_pct(cut) <= 1

    def is_2y_low(self, cut: int) -> bool:
        return (cut > 0 and self._known(True) and self.cheaper_pct(cut, True) <= 1) or self.is_atl(cut)

    @property
    def tier(self) -> str:
        if self.covered_days < 365 and self.sales_2y < 3:
            return "unknown"
        if (self.gap_days and self.gap_days <= 45) or self.sales_2y >= 12:
            return "frequent"
        if self.covered_days >= 540 and self.sales_2y <= 2:
            return "rare"
        return "regular"

    def fake_discount(self, cut: int) -> bool:
        return 0 <= self.raised_days <= 60 and cut > 0

    def rarity(self, cut: int) -> float:
        base = {"rare": 1.0, "regular": 0.5, "frequent": 0.15, "unknown": 0.4}[self.tier]
        return min(1.0, base + (0.2 if self.is_2y_low(cut) else 0))


def _timestamp(value: str) -> dt.datetime:
    stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def parse_history(log: list[dict], today: dt.date, store_low_cut: int = 0, store_low_cents: int = 0,
                  regular_cents: int = 0) -> History:
    """Collapse Steam changes into discount runs; an open final run is current.

    Window lows include the step carried into the window. Counts and medians use
    completed sales whose observed starts fall inside 730 days.
    """
    rows = []
    for row in log:
        try:
            if row.get("shop", {}).get("id", STEAM_SHOP) != STEAM_SHOP:
                continue
            stamp = _timestamp(row["timestamp"])
            deal = row["deal"]
            cut = int(deal.get("cut") or 0)
            if stamp.date() <= today:
                rows.append((stamp, cut, (deal.get("regular") or {}).get("amountInt"),
                             (deal.get("price") or {}).get("amountInt")))
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    rows.sort(key=lambda r: r[0])
    h = History(best_cut=store_low_cut, low_cents=store_low_cents, regular_cents=regular_cents)
    if not rows:
        return h
    h.covered_days = max(0, (today - rows[0][0].date()).days)
    cutoff = today - dt.timedelta(days=730)
    sales = []
    active = None
    previous_regular = None
    for i, (stamp, cut, regular, price) in enumerate(rows):
        day = stamp.date()
        end = rows[i + 1][0].date() if i + 1 < len(rows) else today
        h.best_cut = max(h.best_cut, cut)
        if price:
            h.low_cents = min(h.low_cents, price) if h.low_cents else price
            if day >= cutoff or end > cutoff:
                h.low_2y_cents = min(h.low_2y_cents, price) if h.low_2y_cents else price
        if regular:
            h.regular_cents = regular
        if day >= today - dt.timedelta(days=365) or end > today - dt.timedelta(days=365):
            h.low_1y_cut = max(h.low_1y_cut, cut)
        if day >= cutoff or end > cutoff:
            h.low_2y_cut = max(h.low_2y_cut, cut)
        if regular is not None:
            if previous_regular is not None and regular > previous_regular and (today - day).days <= 120:
                h.raised_days = (today - day).days
            previous_regular = regular
        if cut > 0:
            if active is None:
                active = [day, cut]
            else:
                active[1] = max(active[1], cut)
        elif active is not None:
            sales.append((*active, day))
            active = None
        if day >= cutoff:
            h.points.append((day.isoformat(), cut))
        elif end > cutoff:
            h.points.append((cutoff.isoformat(), cut))
    past = [s for s in sales if s[0] >= cutoff]
    h.sales_2y = len(past)
    h.typical_cut = round(median(s[1] for s in past)) if past else 0
    gaps = [(b[0] - a[0]).days for a, b in zip(past, past[1:])]
    h.gap_days = round(median(gaps)) if gaps else 0
    if sales:
        h.since_last_days = max(0, (today - sales[-1][2]).days)
    return h


def analyze_price_series(rows: list[tuple[str, int, int, int]], today: dt.date | None = None) -> dict:
    """Adapt sparse local observations only when ITAD has no log."""
    return asdict(parse_history([
        {"timestamp": day, "deal": {"cut": cut, "regular": {"amountInt": original}, "price": {"amountInt": _price}}}
        for day, _price, original, cut in rows
    ], today or dt.date.today()))


def _key() -> str:
    return config.cfg.itad_api_key


def available() -> bool:
    return bool(_key())


def _cut(low: float | None, regular: float | None) -> int | None:
    if low is None or not regular or regular <= 0:
        return None
    return max(0, round(100 * (1 - low / regular)))


PACE = 0.2                  # seconds between ITAD calls: its burst limit is far below the documented 1000 / 5 min
_pace_lock = threading.Lock()
_next_call = 0.0


def _request(url: str, **kwargs):
    """Best-effort ITAD request, paced; net handles one short Retry-After retry on 429."""
    global _next_call
    with _pace_lock:
        wait = _next_call - time.monotonic()
        _next_call = max(time.monotonic(), _next_call) + PACE
    if wait > 0:
        time.sleep(wait)
    try:
        return request_json(url, retries=1, **kwargs)
    except Exception:
        return None


def _resolve_ids(appids: list[int]) -> dict[int, str]:
    out, todo = {}, []
    for a in appids:
        cached = _id_cache.get(a, 60 * DAY)
        if cached is None:
            todo.append(a)
        elif cached:
            out[a] = cached
    for i in range(0, len(todo), 200):
        chunk = todo[i: i + 200]
        data = _request(f"{BASE}/lookup/id/shop/{STEAM_SHOP}/v1", params={"key": _key()},
                            payload=[f"app/{a}" for a in chunk])
        if not isinstance(data, dict):
            continue
        for a in chunk:
            gid = data.get(f"app/{a}") if isinstance(data, dict) else None
            _id_cache.set(a, gid or "")
            if gid:
                out[a] = gid
    return out


def _from_cached(cached: dict) -> History:
    valid = {k: v for k, v in cached.items() if k in History.__dataclass_fields__}
    valid["points"] = [tuple(p) for p in valid.get("points", [])]
    return History(**valid)


def _game_log(appid: int, gid: str) -> list[dict]:
    cached = _log_cache.get(appid, 30 * DAY) or {}
    log = cached.get("log", [])
    if stale_ok():                      # first paint: whatever we have; the fresh load fetches the rest
        return log
    if time.time() - cached.get("fetched", 0) <= 3 * DAY:       # the current price comes from Steam itself
        return log
    # ITAD rejects fractional seconds ("Invalid 'since' format"): send whole seconds in UTC
    start = max((_timestamp(r["timestamp"]) for r in log), default=None) or (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1096))
    since = start.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = _request(f"{BASE}/games/history/v2", params={
        "key": _key(), "id": gid, "country": "US", "shops": STEAM_SHOP, "since": since})
    if isinstance(data, list):
        merged = {}
        for row in log + data:
            try:
                stamp = _timestamp(row["timestamp"])
                if not isinstance(row["deal"], dict):
                    continue
                merged[(stamp, row.get("shop", {}).get("id", STEAM_SHOP))] = row
            except (ValueError, TypeError, KeyError, AttributeError):
                continue
        log = sorted(merged.values(), key=lambda r: _timestamp(r["timestamp"]))
        _log_cache.set(appid, {"log": log, "fetched": time.time()})
    return log


def history(appids: list[int], deep: list[int] | None = None) -> dict[int, History]:
    """Batch Steam lows for all games; fetch full logs only for the shortlist."""
    if not available() or not appids:
        return {}
    appids = list(dict.fromkeys(appids))
    shortlist = set(appids if deep is None else deep) & set(appids)
    ids = _resolve_ids(appids)
    result = {a: History() for a in appids}
    todo = []
    for a in appids:
        cached = _prices_cache.get(a, 12 * HOUR)
        if cached is None or not isinstance(cached, dict):
            todo.append(a)
        else:
            result[a] = History(best_cut=cached["best"], low_cents=cached["low"], regular_cents=cached["regular"])
    by_gid = {ids[a]: a for a in todo if a in ids}
    gids = list(by_gid)
    for i in range(0, len(gids), 200):
        data = _request(f"{BASE}/games/prices/v3", params={
            "key": _key(), "country": "US", "shops": STEAM_SHOP, "nondeals": "true"},
            payload=gids[i:i + 200])
        for entry in data if isinstance(data, list) else []:
            a = by_gid.get(entry.get("id"))
            deal = next((d for d in (entry.get("deals") or []) if d.get("shop", {}).get("id") == STEAM_SHOP), None)
            if a is None or not deal:
                continue
            best = max(_cut((deal.get("storeLow") or {}).get("amount"),
                            (deal.get("regular") or {}).get("amount")) or 0, deal.get("cut") or 0)
            low = int((deal.get("storeLow") or {}).get("amountInt") or 0)
            regular = int((deal.get("regular") or {}).get("amountInt") or 0)
            result[a] = History(best_cut=best, low_cents=low, regular_cents=regular)
            _prices_cache.set(a, {"best": best, "low": low, "regular": regular})
    pending = []
    for a in shortlist:
        cached = _hist_cache.get(a, 12 * HOUR)
        if cached is not None:
            h = _from_cached(cached)
            base = result.get(a, History())
            h.best_cut = max(h.best_cut, base.best_cut)
            h.low_cents = min(x for x in (h.low_cents, base.low_cents) if x) if (h.low_cents or base.low_cents) else 0
            h.regular_cents = base.regular_cents or h.regular_cents
            result[a] = h
        else:
            pending.append(a)

    def fetch(a):
        base = result.get(a, History())
        best = base.best_cut
        log = _game_log(a, ids[a]) if a in ids else []
        if not log:
            # our own samples are too sparse to count sales or prove a price hike: keep only the deepest cut
            country = (config.cfg.country or "US").upper()
            local = analyze_price_series(price_history(a, country))
            h = History(best_cut=max(best, local.get("best_cut", 0)), low_cents=base.low_cents,
                        regular_cents=base.regular_cents)
        else:
            h = parse_history(log, dt.date.today(), best, base.low_cents, base.regular_cents)
            h.regular_cents = base.regular_cents or h.regular_cents      # today's base price beats the log's
            _hist_cache.set(a, asdict(h))      # a failed fetch (rate limit, offline) is retried next run
        _prices_cache.set(a, {"best": h.best_cut, "low": h.low_cents, "regular": h.regular_cents})
        return a, h

    with ThreadPoolExecutor(max_workers=3) as pool:
        for a, h in pool.map(fetch, pending):
            result[a] = h
    return result


@dataclass
class Bundle:
    title: str
    shop: str
    url: str
    price_cents: int
    currency: str
    expiry_iso: str | None


def parse_bundles(data: list[dict], gid: str, now: dt.datetime) -> Bundle | None:
    """Cheapest priced tier containing the game across currently active bundles."""
    offers = []
    for entry in data:
        try:
            expiry = entry.get("expiry")
            publish = _timestamp(entry["publish"])
            if publish > now:
                continue
            if expiry:
                if _timestamp(expiry) <= now:
                    continue
            elif publish < now - dt.timedelta(days=365):
                continue
            for tier in entry.get("tiers", []):
                price = tier.get("price")
                if not price or not any(g.get("id") == gid for g in tier.get("games", [])):
                    continue
                cents = price.get("amountInt")
                if cents is None:
                    cents = round(price["amount"] * 100)
                offers.append(Bundle(entry["title"], entry.get("page", {}).get("name", ""),
                                     entry.get("url", ""), cents, price["currency"], expiry))
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
    return min(offers, key=lambda b: b.price_cents) if offers else None


def bundles(appids: list[int]) -> dict[int, Bundle]:
    if not available() or not appids:
        return {}
    out, todo = {}, []
    country = (config.cfg.country or "US").upper()
    now = dt.datetime.now(dt.timezone.utc)
    for a in dict.fromkeys(appids):
        cached = _bundle_cache.get(f"{country}:{a}", 12 * HOUR)
        if cached is None:
            todo.append(a)
        elif cached:
            b = Bundle(**cached)
            if not b.expiry_iso or _timestamp(b.expiry_iso) > now:
                out[a] = b
    if stale_ok():
        return out
    ids = _resolve_ids(todo)

    def fetch(a):
        gid = ids.get(a)
        data = _request(f"{BASE}/games/bundles/v2", params={
            "key": _key(), "id": gid, "country": country, "expired": "true"}) if gid else []
        b = parse_bundles(data, gid, now) if isinstance(data, list) else None
        if isinstance(data, list):                # only a real answer is remembered
            _bundle_cache.set(f"{country}:{a}", asdict(b) if b else {})
        return a, b

    with ThreadPoolExecutor(max_workers=3) as pool:
        for a, b in pool.map(fetch, todo):
            if b:
                out[a] = b
    return out


# --------------------------------------------------------------------------- cheaper elsewhere

# Authorised stores only (ITAD lists no key resellers); GamesPlanet regional storefronts included.
OFFICIAL_SHOPS = {35: "GOG", 37: "Humble", 6: "Fanatical", 36: "Green Man Gaming", 16: "Epic Games",
                  48: "Microsoft Store", 52: "EA app", 62: "Ubisoft Store", 64: "WinGameStore", 50: "Nuuvem",
                  26: "GamesPlanet", 27: "GamesPlanet", 28: "GamesPlanet", 29: "GamesPlanet"}
_else_cache = Cache("itad_elsewhere", volatile=True)


@dataclass
class Elsewhere:
    shop: str
    pct: int          # how much cheaper than Steam, in %
    url: str


def elsewhere_enabled(setting: str, country: str) -> bool:
    """'auto' only where Steam has no regional discount pricing — elsewhere keys are usually pricier
    or region-locked in TR, AR, CIS, IN, BR …"""
    if setting in ("on", "off"):
        return setting == "on"
    from . import region
    return region.group(country) == "USD" or region.currency_marker(country) in {"€", "£", "CHF", "C$", "A$", "NZ$"}


def elsewhere(appids: list[int], country: str) -> dict[int, Elsewhere]:
    if not available() or not appids:
        return {}
    out, todo = {}, []
    for a in appids:
        cached = _else_cache.get(f"{country}:{a}", 6 * HOUR)
        if cached is None:
            todo.append(a)
        elif cached:
            out[a] = Elsewhere(**cached)
    ids = _resolve_ids(todo)
    by_gid = {gid: a for a, gid in ids.items()}
    shops = ",".join(str(s) for s in [STEAM_SHOP, *OFFICIAL_SHOPS])
    gids = list(by_gid)
    for i in range(0, len(gids), 200):
        data = request_json(f"{BASE}/games/prices/v3", params={"key": _key(), "country": country, "shops": shops},
                            payload=gids[i: i + 200]) or []
        for entry in data if isinstance(data, list) else []:
            a = by_gid.get(entry.get("id"))
            deals = entry.get("deals") or []
            steam = next((d for d in deals if d.get("shop", {}).get("id") == STEAM_SHOP), None)
            others = [d for d in deals if d.get("shop", {}).get("id") in OFFICIAL_SHOPS]
            if a is None or not steam or not others:
                continue
            best = min(others, key=lambda d: d["price"]["amount"])
            sp, op = steam["price"]["amount"], best["price"]["amount"]
            if sp > 0 and op < sp * 0.97:
                e = Elsewhere(OFFICIAL_SHOPS[best["shop"]["id"]], round(100 * (1 - op / sp)), best.get("url", ""))
                out[a] = e
                _else_cache.set(f"{country}:{a}", e.__dict__)
    for a in todo:
        if a not in out:
            _else_cache.set(f"{country}:{a}", {})
    return out
