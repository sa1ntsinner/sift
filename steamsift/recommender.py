"""Deal-first ranking engine and taste personalization model.

Pipeline
  1. Deal Value – Objective Steam deal intelligence: All-Time Low (ATL) and
                  2-Year Low (2YL) status, discount cadence/rarity (rare vs
                  perennial sales), review quality (Wilson lower bound), and
                  bundle / Complete-the-Set value.
  2. TagSpace   – TF-IDF over Steam community tags (weights from the store), so
                  ubiquitous tags like "Singleplayer" carry little signal and
                  distinctive ones like "Automobile Sim" carry a lot.
  3. Profile    – Weighted sum of game vectors from implicit + explicit signals:
                  playtime (log-scaled, recency-decayed), last-2-weeks play,
                  wishlist intent, and negatives for games you tried and
                  dropped or explicitly hid ("don't recommend").
  4. Score      – Deal quality & review quality first (75%), taste affinity &
                  intent second (25%) so extraordinary Steam deals surface
                  reliably while still reflecting personal preferences.
"""
from __future__ import annotations

import datetime as dt
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field

from . import config, region
from .i18n import t
from .itad import History, _timestamp
from .steam import Item, Library, local_tag

# Final ranking: objective deal_score already contains review quality; taste is secondary.
W_DEAL, W_AFFINITY = 0.75, 0.25
W_DEPTH, W_RARITY, W_QUALITY, W_BUNDLE = 0.45, 0.20, 0.25, 0.10
NOVELTY_SWEET = 0.66   # discover: new, but still with a bridge back to your taste


# --------------------------------------------------------------------------- tag space

@dataclass
class TagSpace:
    idf: dict[str, float]
    default_idf: float
    mean: dict[str, float] = field(default_factory=dict)   # average game vector ("everyone's taste")

    @classmethod
    def build(cls, tag_sets: list[dict[str, float]]) -> "TagSpace":
        n = max(1, len(tag_sets))
        df = Counter(tag for tags in tag_sets for tag in tags)
        idf = {tag: math.log((n + 1) / (c + 1)) + 1.0 for tag, c in df.items()}
        space = cls(idf, math.log(n + 1) + 1.0)
        mean: dict[str, float] = {}
        for tags in tag_sets:
            for tag, x in space.vec(tags).items():
                mean[tag] = mean.get(tag, 0.0) + x / n
        space.mean = mean
        return space

    def vec(self, tags: dict[str, float]) -> dict[str, float]:
        if not tags:
            return {}
        top = max(tags.values()) or 1
        v = {tag: (w / top) ** 0.7 * self.idf.get(tag, self.default_idf) for tag, w in tags.items() if w > 0}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {tag: x / norm for tag, x in v.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine for already L2-normalised vectors."""
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(tag, 0.0) for tag, x in a.items())


# --------------------------------------------------------------------------- profile

@dataclass
class Signal:
    appid: int | None
    name: str
    kind: str          # played | seed | wishlist | interest | dropped | hidden
    weight: float
    vec: dict[str, float]
    hours: float = 0.0
    franchises: list[str] = field(default_factory=list)


CENTERING = 0.8  # how much of the "average game" to subtract from each signal


def centered(vec: dict[str, float], mean: dict[str, float]) -> dict[str, float]:
    out = dict(vec)
    for tag, m in mean.items():
        out[tag] = out.get(tag, 0.0) - CENTERING * m
    return out


@dataclass
class Profile:
    vector: dict[str, float]
    signals: list[Signal]
    mean: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        self.norm2 = sum(x * x for x in self.vector.values()) or 1.0
        self.by_appid = {s.appid: s for s in self.signals if s.appid}
        self.anchors = sorted((s for s in self.signals if s.kind in ("played", "seed") and s.vec and s.weight > 1.0),
                              key=lambda s: -s.weight)[:40]
        self.franchise_hours: dict[str, float] = {}
        for s in self.signals:
            if s.kind == "played":
                for f in s.franchises:
                    self.franchise_hours[f] = self.franchise_hours.get(f, 0) + s.hours

    def cosine(self, v: dict[str, float], exclude: int | None = None) -> float:
        """Cosine to the profile, leaving out the item's own contribution (no self-boost)."""
        if not v:
            return 0.0
        dot = sum(x * self.vector.get(tag, 0.0) for tag, x in v.items())
        norm2 = self.norm2
        own = self.by_appid.get(exclude) if exclude else None
        if own and own.vec:
            c = centered(own.vec, self.mean)
            ps = sum(x * self.vector.get(tag, 0.0) for tag, x in c.items())
            dot -= own.weight * sum(x * c.get(tag, 0.0) for tag, x in v.items())
            norm2 = max(1e-9, norm2 - 2 * own.weight * ps + own.weight ** 2 * sum(x * x for x in c.values()))
        return dot / math.sqrt(norm2)

    def top_tags(self, n: int = 10, include_meta: bool = False) -> list[tuple[str, float]]:
        pos = [(tag, w) for tag, w in self.vector.items() if w > 0 and (include_meta or tag not in META_TAGS)]
        pos.sort(key=lambda x: -x[1])
        total = sum(w for _, w in pos) or 1.0
        return [(tag, w / total) for tag, w in pos[:n]]


def _recency(rtime: int, now: float) -> float:
    if not rtime:
        return 0.35
    age_days = max(0.0, (now - rtime) / 86400)
    return 0.35 + 0.65 * 0.5 ** (age_days / 365)


HIDDEN_WEIGHT = -0.6    # "not my kind of game": a firmer negative than a silent drop
SEED_WEIGHT = 2.5       # a favourite picked during setup ≈ a game played ~10h recently
INTEREST_WEIGHT = 0.35  # you opened it in the store / asked for details: mild positive


def build_profile(lib: Library, meta: dict[int, Item], space: TagSpace, hidden: dict[int, dict] | None = None,
                  fallback_hours: float | None = None, seeds: list[int] | None = None,
                  interest: dict[int, int] | None = None) -> Profile:
    now = time.time()
    signals: list[Signal] = []

    for aid, g in lib.my_games.items():
        hours = g.get("playtime_forever", 0) / 60 or (fallback_hours or 0.0)
        item = meta.get(aid)
        vec = space.vec(item.tags) if item else {}
        if not vec:
            continue
        franchises = item.franchises if item else []
        age_days = (now - g.get("rtime_last_played", 0)) / 86400 if g.get("rtime_last_played") else 9999
        if hours >= 1:
            w = math.log1p(min(hours, 200)) * _recency(g.get("rtime_last_played", 0), now)
            w += 0.6 * math.log1p(g.get("playtime_2weeks", 0) / 60)
            signals.append(Signal(aid, g["name"], "played", w, vec, hours, franchises))
        elif 0.05 <= hours < 1 and age_days > 21 and not (item and item.is_free):
            signals.append(Signal(aid, g["name"], "dropped", -0.3, vec, hours, franchises))

    for w in lib.wishlist:
        item = meta.get(w["appid"])
        if item and item.tags:
            signals.append(Signal(item.appid, item.name, "wishlist", 0.45, space.vec(item.tags), 0, item.franchises))

    for aid in seeds or []:
        item = meta.get(aid)
        if item and item.tags and aid not in lib.my_games:
            signals.append(Signal(aid, item.name, "seed", SEED_WEIGHT, space.vec(item.tags), 10.0, item.franchises))

    for aid, n in (interest or {}).items():
        item = meta.get(aid)
        if item and item.tags and aid not in (hidden or {}):
            signals.append(Signal(aid, item.name, "interest", INTEREST_WEIGHT * min(3, n), space.vec(item.tags)))

    for aid, h in (hidden or {}).items():
        item = meta.get(aid)
        if h.get("reason") == "taste" and item and item.tags:
            signals.append(Signal(aid, item.name, "hidden", HIDDEN_WEIGHT, space.vec(item.tags)))

    vector: dict[str, float] = {}
    for s in signals:
        for tag, x in centered(s.vec, space.mean).items():
            vector[tag] = vector.get(tag, 0.0) + s.weight * x
    return Profile(vector, signals, space.mean)


# --------------------------------------------------------------------------- scoring

def wilson_lower(pct: int | None, n: int, z: float = 1.96) -> float | None:
    if pct is None or n <= 0:
        return None
    p = pct / 100
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom


def _depth(cut: int, hist: History | None) -> float:
    """Discount depth, independent of taste and review quality (0..1)."""
    base = (max(0, min(100, cut)) / 100) ** 0.9
    if hist and hist.best_cut > 0:
        return 0.5 * base + 0.5 * min(1.0, max(0, cut) / hist.best_cut) ** 1.5
    return base


def deal_value(cut: int, hist: History | None, item: Item | None = None) -> float:
    """Existing discovery depth formula, retained independently of deal_score."""
    base = (max(0, cut) / 100) ** 0.9
    if hist and hist.best_cut > 0:
        ratio = min(1.0, cut / hist.best_cut)
        val = 0.45 * base + 0.55 * (ratio ** 1.5)
        if hist.is_atl(cut):
            val += 0.06
        elif hist.low_2y_cut > 0 and hist.is_2y_low(cut):
            ratio_2y = min(1.0, cut / hist.low_2y_cut)
            val = max(val, 0.45 * base + 0.50 * (ratio_2y ** 1.4)) + 0.04
        if hist.tier == "rare":
            val += 0.06 * hist.rarity(cut)
        elif hist.tier == "frequent" and not hist.is_atl(cut):
            val -= 0.05
    else:
        val = base
    if item is not None:
        if item.bundle_discount > 0:
            val += min(0.06, item.bundle_discount / 250)
        elif item.complete_the_set or item.included_games > 1:
            val += 0.03
    return max(0.0, min(1.0, val))


@dataclass
class Verdict:
    kind: str = ""
    reason: str = ""
    value: int = 0


def verdict(cut: int, hist: History | None, sale_next=None, bundle=None,
            price_cents: int = 0, currency: str = "", today: dt.date | None = None) -> Verdict:
    """Five levels, first match wins (prices compared in what you pay, not only in percent):

    nope  the base price went up in the last 60 days (fake discount), or it has been 30%+ cheaper
    hot   record price that rarely comes back · lowest in 2 years for a rarely discounted game ·
          a rare sale at its usual depth · a cheaper active third-party bundle
    great record price, but it comes back every few weeks
    ok    record price with too little history to judge · an ordinary discount for this game
    meh   it has been 12–30% cheaper · a big Steam sale starts within 21 days and this cut is small
    No history yields an empty verdict.
    """
    if not hist or not hist._known() or cut <= 0:
        return Verdict()
    if hist.fake_discount(cut):
        return Verdict("nope", "fake", hist.raised_days)
    if hist.is_atl(cut):
        if hist.tier == "frequent":       # a record price that comes back every few weeks is no reason to hurry
            return Verdict("great", "returns", hist.gap_days or round(730 / max(1, hist.sales_2y)))
        if hist.tier == "unknown":        # record price, but no log to say how often it happens
            return Verdict("ok", "atl_unknown", hist.best_cut)
        return Verdict("hot", "atl", hist.best_cut)
    if hist.is_2y_low(cut) and hist.tier != "frequent":
        return Verdict("hot", "low_2y", hist.low_2y_cut)
    if hist.tier == "rare" and cut >= hist.typical_cut:
        return Verdict("hot", "rare_first" if not hist.sales_2y else "rare", hist.sales_2y)
    if _cheaper_bundle(bundle, price_cents, currency, today):
        return Verdict("hot", "bundle", bundle.price_cents)
    cheaper = hist.cheaper_pct(cut)
    if hist.low_cents and hist.regular_cents and hist.now_cents(cut) - hist.low_cents < 100:
        cheaper = 0                       # less than a dollar (US) apart: not worth waiting for
    if cheaper >= 30:
        return Verdict("nope", "cheaper_before", cheaper)
    if sale_next and getattr(sale_next, "kind", "sale") == "sale":
        days = (sale_next.start - (today or dt.date.today())).days
        if 0 <= days <= 21 and cut < max(hist.typical_cut, hist.low_1y_cut):
            return Verdict("meh", "sale_soon", days)
    if cheaper >= 12 and hist.tier != "rare":
        return Verdict("meh", "cheaper_before", cheaper)
    return Verdict("ok", "typical", hist.typical_cut or hist.best_cut)


def _cheaper_bundle(bundle, price_cents: int, currency: str, today=None) -> bool:
    if not bundle or bundle.currency != currency or bundle.price_cents >= price_cents:
        return False
    now = dt.datetime.combine(today, dt.time(), dt.timezone.utc) if today else dt.datetime.now(dt.timezone.utc)
    try:
        return not bundle.expiry_iso or _timestamp(bundle.expiry_iso) > now
    except (TypeError, ValueError):
        return False


# Tags describing format rather than taste: kept in the model, hidden from explanations.
META_TAGS = {
    "Singleplayer", "Multiplayer", "Great Soundtrack", "Indie", "Casual", "Controller", "Free to Play",
    "Early Access", "Co-op", "Online Co-Op", "Massively Multiplayer", "VR", "3D", "2D", "Moddable",
    "Beautiful", "Classic", "Masterpiece", "Addictive", "Replay Value", "Cult Classic", "Funny",
    "Memes", "Short", "Remake", "Sequel", "Realistic",
}


@dataclass
class Rec:
    item: Item
    cos: float
    quality: float
    intent: float
    why: str
    is_wish: bool
    hist: History | None = None
    verdict: Verdict = field(default_factory=Verdict)
    affinity: float = 0.0
    score: float = 0.0
    deal_score: float = 0.0     # objective deal intelligence score (0..100, taste-agnostic)
    note: str = ""
    similarity: float = 0.0     # to the closest game you already love (0..1)
    explore: float = 0.0        # 0 = familiar … 1 = adventurous (profile setting)
    extras: dict = field(default_factory=dict)   # elsewhere / third-party / calendar / bundle hints for renderers
    mode: str = "taste"         # taste (picks, wishlist) | discover (new for you — see discover.py)
    novelty: float = 0.0        # discover: 0 = your usual … 1 = completely new
    lane: str = ""              # discover: the genre that is new for you ("" = more to explore)
    penalty: float = 1.0        # discover: fades games shown in earlier weeks that you passed on

    @property
    def taste_pct(self) -> int:
        return round(100 * self.affinity)

    @property
    def is_atl(self) -> bool:
        return bool(self.hist and self.hist.is_atl(self.item.cut))

    @property
    def is_2y_low(self) -> bool:
        return bool(self.hist and self.hist.is_2y_low(self.item.cut))

    @property
    def is_rare_sale(self) -> bool:
        return bool(self.hist and self.hist.tier == "rare")

    def rescore(self) -> None:
        country = config.cfg.country or "US"
        marker = region.currency_marker(country)
        currency = {"$": "USD", "€": "EUR", "£": "GBP", "руб": "RUB", "₸": "KZT",
                    "R$": "BRL", "C$": "CAD", "A$": "AUD", "NZ$": "NZD", "₹": "INR",
                    "¥": "JPY", "₩": "KRW", "zł": "PLN", "Mex$": "MXN", "CLP$": "CLP",
                    "COL$": "COP", "HK$": "HKD", "S$": "SGD", "NT$": "TWD"}.get(marker, marker)
        currency = {"CN": "CNY", "JP": "JPY"}.get(country.upper(), currency)
        d = _depth(self.item.cut, self.hist)
        rarity = self.hist.rarity(self.item.cut) if self.hist else 0.4
        self.verdict = verdict(self.item.cut, self.hist, self.extras.get("sale_next"),
                               self.extras.get("bundle3p"), self.item.final_cents, currency)
        bundle = self.extras.get("bundle3p")
        bundle_value = float(bool(self.item.bundle_discount > 0 or self.item.complete_the_set
                                  or self.item.included_games > 1 or
                                  _cheaper_bundle(bundle, self.item.final_cents, currency)))
        obj = W_DEPTH * d + W_RARITY * rarity + W_QUALITY * self.quality + W_BUNDLE * bundle_value
        if self.verdict.reason == "fake":
            obj *= 0.6
        self.deal_score = round(100 * max(0, min(1.0, obj)), 1)

        if self.mode == "discover":
            d = deal_value(self.item.cut, self.hist, self.item)
            fit = 1 - min(1.0, abs(self.novelty - NOVELTY_SWEET) / NOVELTY_SWEET)
            confidence = min(1.0, math.log10(max(10, self.item.review_count)) / 5)
            s = 0.42 * self.quality + 0.25 * d + 0.18 * fit + 0.15 * confidence
            if self.item.early_access:
                s *= 0.9
            self.score = round(100 * s * self.penalty, 1)
            return
        # Explore keeps taste alignment but discounts near-clones of what you already play.
        aff = self.affinity * (1 - self.explore * max(0.0, self.similarity - 0.3) / 0.7)
        taste = 100 * max(0, min(1, aff))
        self.score = round(min(100, W_DEAL * self.deal_score + W_AFFINITY * taste
                               + (5 if self.is_wish else 0)), 1)



_TRADEMARKS = re.compile(r"[™®©]")


def short_name(name: str, limit: int = 26) -> str:
    name = _TRADEMARKS.sub("", name).strip()
    return name if len(name) <= limit else name[: limit - 1].rstrip() + "…"


def make_rec(item: Item, profile: Profile, space: TagSpace, is_wish: bool, explore: float = 0.0) -> Rec:
    v = space.vec(item.tags)
    cos = profile.cosine(v, exclude=item.appid)

    wl = wilson_lower(item.review_pct, item.review_count)
    quality = 0.35 if wl is None else max(0.0, min(1.0, (wl - 0.50) / 0.45))

    reasons: list[str] = []
    intent = 1.0 if is_wish else 0.0
    nearest = max((cosine(v, a.vec) for a in profile.anchors if a.appid != item.appid), default=0.0)
    fr = next((f for f in item.franchises if profile.franchise_hours.get(f, 0) >= 2), None)
    if fr:
        intent = max(intent, 0.6)
        reasons.append(t("why_series", name=short_name(fr, 22)))
    else:
        best, best_sim = None, 0.55
        for a in profile.anchors:
            if a.appid == item.appid:
                continue
            sim = cosine(v, a.vec)
            if sim > best_sim:
                best, best_sim = a, sim
        if best:
            reasons.append(t("why_like", name=short_name(best.name)))

    contrib = sorted(((tag, x * profile.vector.get(tag, 0.0)) for tag, x in v.items()), key=lambda c: -c[1])
    tags = [local_tag(tag).lower() for tag, c in contrib if c > 0 and tag not in META_TAGS][:2]
    if tags:
        reasons.append(", ".join(tags))
    return Rec(item=item, cos=cos, quality=quality, intent=intent, why=" · ".join(reasons), is_wish=is_wish,
               similarity=nearest, explore=explore)


def calibrate(recs: list[Rec]) -> None:
    """Map cosine to 0..1 using the spread of today's candidate pool."""
    if not recs:
        return
    vals = sorted(r.cos for r in recs)

    def pct(q: float) -> float:
        return vals[min(len(vals) - 1, int(q * (len(vals) - 1)))]

    lo, hi = pct(0.15), pct(0.97)
    span = max(1e-6, hi - lo)
    for r in recs:
        r.affinity = max(0.0, min(1.0, (r.cos - lo) / span))
        r.rescore()


def diversify(recs: list[Rec], per_franchise: int = 1) -> list[Rec]:
    """Keep the best entry per franchise up top; the rest drop to the end."""
    seen: Counter = Counter()
    head, tail = [], []
    for r in recs:
        key = r.item.franchises[0] if r.item.franchises else None
        if key and seen[key] >= per_franchise:
            tail.append(r)
            continue
        if key:
            seen[key] += 1
        head.append(r)
    return head + tail
