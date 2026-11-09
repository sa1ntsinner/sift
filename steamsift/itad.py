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
from .net import on_hold, request_json

BASE = "https://api.isthereanydeal.com"
STEAM_SHOP = 61
_id_cache = Cache("itad_ids")
_hist_cache = Cache("itad_history_v6", volatile=True)   # v6: raised_from (the base price before a raise)
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
    raised_from: int = 0        # US base price before that raise (cents; 0 = unknown)
    covered_days: int = 0
    points: list[tuple[str, int]] = field(default_factory=list)
    regular_cents: int = 0      # current US base price (latest in the log, or ITAD's current deal)
    low_cents: int = 0          # lowest US price ever paid (log or ITAD storeLow)
    low_2y_cents: int = 0       # lowest US price in the last 730 days
    last_day: str = ""          # date of the log's latest change
    last_cut: int = 0           # the cut it changed to
    runs: list = field(default_factory=list)    # finished sales in 730 days: [start date, lowest US cents]

    # How often a price comes back is counted at that price: a game on sale every month at −50% that hit −80%
    # once has seen −80% once, not every month. "Similar" is within 12% (the same band the verdict calls OK):
    # GTFO drops 3–4% every month, so each sale is a new record, but a similar price is back every month.
    SIMILAR = 0.12

    def tolerance(self, cents: int) -> int:
        """Prices this close count as the same price: 3%, at least 25 cents."""
        return max(25, round(cents * 0.03))

    def _starts_at(self, cents: int) -> list[dt.date]:
        top = cents * (1 + self.SIMILAR)
        return sorted(dt.date.fromisoformat(day) for day, low in self.runs if low <= top)

    def times_at(self, cents: int) -> int:
        """Finished sales in two years at a similar price or lower."""
        return len(self._starts_at(cents))

    def gap_at(self, cents: int) -> int:
        """Typical days between sales at this price or lower (0 = fewer than two)."""
        starts = self._starts_at(cents)
        gaps = [(b - a).days for a, b in zip(starts, starts[1:])]
        return round(median(gaps)) if gaps else 0

    def last_at(self, cents: int, today: dt.date | None = None) -> int:
        """Days since the last sale at this price or lower started (-1 = none in two years)."""
        starts = self._starts_at(cents)
        return ((today or dt.date.today()) - starts[-1]).days if starts else -1

    def usual_cents(self, today: dt.date | None = None) -> int:
        """The game's usual sale price: the median low of its sales in the last year (0 = fewer than two).

        Backtested on 3,400 sale starts (2026-11): a price 12%+ above it got 12% cheaper within 90 days in 53-67% of
        cases, a price at or below it in 14-18%. The two-year low is a worse yardstick: a one-off low a year ago
        rarely comes back (22% within 90 days at 30%+ above it)."""
        day = today or dt.date.today()
        lows = [low for start, low in self.runs if (day - dt.date.fromisoformat(start)).days <= 365]
        return round(median(lows)) if len(lows) >= 2 else 0

    def next_sale(self, today: dt.date, ends: dt.date | None = None,
                  sales: list[tuple[dt.date, str]] | None = None) -> tuple[dt.date | None, str]:
        """When the next sale is likely to start: (day, the Steam-wide sale it falls on or "").

        The game's own rhythm (the median gap between its sale starts), but not within 28 days of the end of a
        sale (Steam's cooldown between discounts), or the next Steam-wide sale when that comes first. `ends` is
        the end of the sale running now. A day that has already passed means "any day now": today is returned.
        Backtest (2026-11, 11,600 sales): within a week of the real start in 62% of cases, within two in 77%."""
        on_sale = bool(self.points) and self.points[-1][1] > 0
        start = None
        if on_sale:
            for day, cut in reversed(self.points):
                if cut <= 0:
                    break
                start = dt.date.fromisoformat(day)
            end = max(ends or today, today)
        else:
            start = dt.date.fromisoformat(self.runs[-1][0]) if self.runs else None
            end = today - dt.timedelta(days=self.since_last_days) if self.since_last_days else today
        rhythm = None
        if start and self.gap_days:
            rhythm = max(start + dt.timedelta(days=self.gap_days), end + dt.timedelta(days=28), today)
        season = next(((day, name) for day, name in sorted(sales or []) if day > end and day >= today), None)
        if season and (rhythm is None or season[0] <= rhythm + dt.timedelta(days=3)):
            return season
        return rhythm, ""

    def by_price(self) -> bool:
        """The log is long enough and has US prices: judge in what you pay."""
        return self.covered_days >= 365 and bool(self.regular_cents and self.low_2y_cents)

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
        """The base price went up in the last 60 days and the sale only takes it back: you pay at least 90% of the
        old full price. A raise followed by a real cut below the old price is a sale like any other."""
        if not (0 <= self.raised_days <= 60 and cut > 0):
            return False
        return not (self.raised_from and self.regular_cents) or self.now_cents(cut) >= 0.9 * self.raised_from

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
    h.last_day, h.last_cut = rows[-1][0].date().isoformat(), rows[-1][1]
    cutoff = today - dt.timedelta(days=730)
    sales = []
    active = None
    active_low = 0
    previous_regular = None
    last_regular = None
    for i, (stamp, cut, regular, price) in enumerate(rows):
        day = stamp.date()
        end = rows[i + 1][0].date() if i + 1 < len(rows) else today
        last_regular = regular or last_regular
        if not price and last_regular:
            price = round(last_regular * (100 - cut) / 100)
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
                h.raised_from = previous_regular
            previous_regular = regular
        if cut > 0:
            if active is None:
                active, active_low = [day, cut], price or 0
            else:
                active[1] = max(active[1], cut)
                active_low = min(x for x in (active_low, price) if x) if (active_low or price) else 0
        elif active is not None:
            sales.append((*active, day))
            if active_low and day > cutoff:
                h.runs.append([active[0].isoformat(), active_low])
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


QUIET_DAYS = 365


def trusted(h: History | None, cut: int, today: dt.date | None = None) -> History | None:
    """The log, or nothing when ITAD has lost track of the game.

    Steam has the game on sale, but the log's last change is a return to full price a year ago:
    ITAD stopped following this product (seen on Resident Evil 6: its log, low and base price were all stale).
    Its "no sales in two years" would read as rare, its old base price as "was cheaper". No verdict is honest.
    ponytail: a year of silence is the signal. A shorter gap would also catch a sale that started after
    the last log fetch (logs refresh every 3 days). Pass the sale start here if a tighter rule is needed."""
    if not h or cut <= 0 or not h.last_day or h.last_cut > 0:
        return h
    if ((today or dt.date.today()) - dt.date.fromisoformat(h.last_day)).days <= QUIET_DAYS:
        return h
    return None


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


# ITAD counts a key's calls per five minutes, all endpoints together: 1000 for an account with a verified e-mail,
# about 120 without one (measured 2026-11: the 123rd call got 429 with Retry-After for the rest of the window).
# Past the limit every call fails for minutes, so sift counts its own calls. It starts with BUDGET, doubles it while
# ITAD keeps answering, and on the first 429 remembers how far it got (kept a month): each key runs at its own speed.
BUDGET, BUDGET_MAX, WINDOW = 105, 900, 300
_calls: list[float] = []
_calls_lock = threading.Lock()
_limit_cache = Cache("itad_limit")


def _limit() -> tuple[int, bool]:
    """(calls allowed per window, whether a 429 has shown the real limit)."""
    saved = _limit_cache.get("calls", 30 * DAY)
    if isinstance(saved, dict) and saved.get("calls"):
        return int(saved["calls"]), bool(saved.get("known"))
    return BUDGET, False


def budget_left() -> int:
    """ITAD calls this process may still make in the current five minutes."""
    with _calls_lock:
        edge = time.monotonic() - WINDOW
        _calls[:] = [at for at in _calls if at > edge]
        limit, known = _limit()
        if len(_calls) >= limit and not known and limit < BUDGET_MAX:
            limit = min(BUDGET_MAX, limit * 2)          # every call so far was answered: try twice as far
            _limit_cache.set("calls", {"calls": limit, "known": False})
        return max(0, limit - len(_calls))


def _request(url: str, **kwargs):
    """Best-effort ITAD request inside the call budget; net handles one short Retry-After retry on 429."""
    if stale_ok() or on_hold(url) or not budget_left():
        return None
    with _calls_lock:
        _calls.append(time.monotonic())
    try:
        data = request_json(url, retries=1, **kwargs)
    except Exception:
        return None
    if data is None and on_hold(url):                   # rate limited just now: this is as far as the key goes
        with _calls_lock:
            reached = len(_calls) - 10
            # a 429 after a handful of calls is someone else's doing (another sift running on the same key)
            if reached >= 50 and (reached < _limit()[0] or not _limit()[1]):
                _limit_cache.set("calls", {"calls": reached, "known": True})
    return data


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


# --------------------------------------------------------------------------- the whole sale

FEED_PAGES = 20             # × 200 Steam discounts, the most popular games first (about one in six of all of them)
FEED_TTL = 2 * HOUR         # prices come from Steam itself: the feed says what is on sale and since when
_feed_cache = Cache("itad_feed_v1", volatile=True)
_app_cache = Cache("itad_apps_v2")      # ITAD game id -> its Steam appids ([] = no Steam app)


@dataclass
class Deal:
    """One Steam discount in ITAD's deals list (US prices)."""
    appid: int
    gid: str
    rank: int               # place by popularity among today's discounts (1 = the most wanted game)
    cut: int
    price: int
    regular: int
    store_low: int          # Steam's lowest price ever
    started: float          # when the current price began (unix time)


def _apps_of(gids: list[str]) -> dict[str, list[int]]:
    """Steam appids for ITAD game ids (cached; 200 per call). ITAD files regional and legacy apps under one game
    (Borderlands 2 has three), and the first is not always the one Steam sells: all are returned."""
    out, todo = {}, []
    for gid in gids:
        cached = _app_cache.get(gid, 90 * DAY)
        if cached is None:
            todo.append(gid)
        elif cached:
            out[gid] = cached
    for i in range(0, len(todo), 200):
        chunk = todo[i: i + 200]
        data = _request(f"{BASE}/lookup/shop/{STEAM_SHOP}/id/v1", params={"key": _key()}, payload=chunk)
        if not isinstance(data, dict):
            continue
        for gid in chunk:
            apps = [int(x[4:]) for x in data.get(gid) or [] if isinstance(x, str) and x.startswith("app/")
                    and x[4:].isdigit()][:6]
            _app_cache.set(gid, apps)
            if apps:
                out[gid] = apps
                for appid in apps:
                    _id_cache.set(appid, gid)
    return out


def feed() -> dict[int, Deal]:
    """Steam's discounts by popularity, from ITAD's deals list: the candidate pool beyond Steam's own top sellers,
    and for each game its Steam low and the start of its sale (which says whether a cached price log is complete).

    Twenty calls, kept two hours. An empty answer (no key, rate limit) only narrows the pool."""
    if not available():
        return {}
    cached = _feed_cache.get("US", FEED_TTL)
    if cached is None and not stale_ok():
        def page(n: int):
            data = _request(f"{BASE}/deals/v2", params={
                "key": _key(), "country": "US", "shops": STEAM_SHOP, "limit": 200, "offset": n * 200,
                "sort": "rank", "mature": "true"})
            return data.get("list", []) if isinstance(data, dict) else None
        with ThreadPoolExecutor(max_workers=4) as pool:
            pages = list(pool.map(page, range(FEED_PAGES)))
        rows = []
        for games in pages:
            for g in games or []:
                try:
                    d = g["deal"]
                    if g.get("type") not in ("game", None) or not d.get("cut"):
                        continue
                    rows.append([g["id"], len(rows) + 1, int(d["cut"]), int(d["price"]["amountInt"]),
                                 int(d["regular"]["amountInt"]), int((d.get("storeLow") or {}).get("amountInt") or 0),
                                 _timestamp(d["timestamp"]).timestamp()])
                except (KeyError, TypeError, ValueError, AttributeError):
                    continue
        if pages and pages[0]:              # a list without its head is not worth keeping
            _feed_cache.set("US", rows)
            cached = rows
    apps = _apps_of([row[0] for row in cached or []])
    out: dict[int, Deal] = {}
    for gid, rank, cut, price, regular, low, started in cached or []:
        for appid in apps.get(gid, []):
            if appid not in out:
                out[appid] = Deal(appid, gid, rank, cut, price, regular, low, started)
    return out


# --------------------------------------------------------------------------- price logs

LOG_DAYS = 45       # a cached log older than this is dropped and fetched whole again
QUIET_REFRESH = 5 * DAY     # how old a log may be when the start of the current sale is unknown


def _log_complete(fetched: float, started: float) -> bool:
    """Nothing can be missing from a log fetched after the current sale began (or within two days before it:
    no sale starts and ends that fast). Without the sale's start, a log is good for a few days."""
    if started:
        return fetched >= started - 2 * DAY
    return time.time() - fetched <= QUIET_REFRESH


def _game_log(appid: int, gid: str, started: float = 0) -> list[dict]:
    cached = _log_cache.get(appid, LOG_DAYS * DAY) or {}
    log = cached.get("log", [])
    if stale_ok():                      # first paint: whatever we have; the fresh load fetches the rest
        return log
    if log and _log_complete(cached.get("fetched", 0), started):
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


NEW_LOGS = 5000     # first-time price logs per run beyond the shortlist: in practice ITAD's call budget decides
RESERVE = 8         # calls left for whatever comes after the logs (bundles, other stores)
unfinished: set[int] = set()    # games whose log is missing or out of date after the last runs: the next run goes on


def history(appids: list[int], deep: list[int] | None = None, cuts: dict[int, int] | None = None,
            deals: dict[int, Deal] | None = None) -> dict[int, History]:
    """Steam lows for all games; full price logs for the shortlist, the most important first.

    `deep` is the shortlist in order of importance. With `cuts` (today's discounts) it grows: every discounted
    game whose log is already cached, and up to NEW_LOGS more, closest to their Steam low first. Without a log a
    game cannot be judged by price and gets "record · little data"; most HOT and GREAT prices hide there.
    `deals` (the feed) gives Steam lows without a call and tells which cached logs are still complete.
    ITAD's call budget decides how many logs one run fetches; a log that could not be refreshed is used as it is."""
    if not available() or not appids:
        return {}
    appids = list(dict.fromkeys(appids))
    deals = deals or {}
    order = [a for a in (appids if deep is None else deep) if a in set(appids)]
    shortlist = set(order)
    result = {a: History() for a in appids}
    todo = []
    for a in appids:
        cached = _prices_cache.get(a, 12 * HOUR)
        deal = deals.get(a)
        if isinstance(cached, dict):
            result[a] = History(best_cut=cached["best"], low_cents=cached["low"], regular_cents=cached["regular"])
        elif deal and cuts and cuts.get(a) == deal.cut:     # the same discount: the same product
            best = max(_cut(deal.store_low, deal.regular) or 0, deal.cut) if deal.store_low else deal.cut
            result[a] = History(best_cut=best, low_cents=deal.store_low, regular_cents=deal.regular)
            _prices_cache.set(a, {"best": best, "low": deal.store_low, "regular": deal.regular})
        else:
            todo.append(a)
    ids = _resolve_ids(appids)
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
    if cuts:
        extra = [a for a in appids if a not in shortlist and cuts.get(a, 0) > 0 and a in ids]
        have = [a for a in extra if _log_cache.get(a, LOG_DAYS * DAY)]

        place = {a: n for n, a in enumerate(appids)}

        def priority(a):
            # at the Steam low first (that is where HOT and GREAT are), then close to it; inside each group the
            # caller's order: the games the user is most likely to want
            h = result[a]
            now = h.now_cents(cuts[a])
            near = now / h.low_cents if now and h.low_cents else 9.0
            return (0 if near <= 1.03 else 1 if near <= 1.15 else 2, place[a])
        kept = set(have)
        new = sorted((a for a in extra if a not in kept), key=priority)[:NEW_LOGS]
        order += sorted(new + have, key=priority)
        shortlist |= kept | set(new)
    pending = []
    for a in order:
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
        deal = deals.get(a)
        on_sale = bool(cuts and cuts.get(a, 0) > 0)
        started = deal.started if deal and on_sale and cuts.get(a) == deal.cut else 0
        spare = budget_left() > RESERVE
        log = _game_log(a, ids[a], started) if a in ids and spare else (_log_cache.get(a, LOG_DAYS * DAY) or {}).get(
            "log", [])
        complete = bool(log) and (stale_ok() or _log_complete((_log_cache.get(a) or {}).get("fetched", 0), started))
        if not complete and a in ids and not stale_ok():
            unfinished.add(a)
        else:
            unfinished.discard(a)
        if not log:
            # our own samples are too sparse to count sales or prove a price hike: keep only the deepest cut
            country = (config.cfg.country or "US").upper()
            local = analyze_price_series(price_history(a, country))
            h = History(best_cut=max(best, local.get("best_cut", 0)), low_cents=base.low_cents,
                        regular_cents=base.regular_cents)
        else:
            h = parse_history(log, dt.date.today(), best, base.low_cents, base.regular_cents)
            h.regular_cents = base.regular_cents or h.regular_cents      # today's base price beats the log's
            if complete:
                _hist_cache.set(a, asdict(h))  # a log that could not be refreshed (rate limit, offline): next run
        _prices_cache.set(a, {"best": h.best_cut, "low": h.low_cents, "regular": h.regular_cents})
        return a, h

    with ThreadPoolExecutor(max_workers=4) as pool:
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
    by_gid = {ids[a]: a for a in todo if a in ids}
    gids = list(by_gid)
    for i in range(0, len(gids), 200):      # one call for 200 games: the active bundles that hold any of them
        chunk = gids[i: i + 200]
        data = _request(f"{BASE}/games/overview/v2", params={"key": _key(), "country": country,
                                                             "shops": STEAM_SHOP}, payload=chunk)
        found = data.get("bundles") if isinstance(data, dict) else None
        if not isinstance(found, list):     # only a real answer is remembered
            continue
        for gid in chunk:
            b = parse_bundles(found, gid, now)
            _bundle_cache.set(f"{country}:{by_gid[gid]}", asdict(b) if b else {})
            if b:
                out[by_gid[gid]] = b
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
        data = _request(f"{BASE}/games/prices/v3", params={"key": _key(), "country": country, "shops": shops},
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
