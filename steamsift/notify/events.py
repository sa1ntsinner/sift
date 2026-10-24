"""What is worth a notification, de-duplication, quiet hours and the digest queue."""
from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import dataclass

from ..db import db
from ..i18n import t
from .cards import Card, sale_name

RENOTIFY_AFTER = 21 * 86400          # the same deal may be announced again after 3 weeks
ORDER = ["wish_target", "wish_lowest", "ending", "pick_strong", "dlc_lowest", "sale_start"]


@dataclass
class Event:
    kind: str
    appid: int
    price_cents: int
    extra: str
    card: Card


def _kind(r) -> str:
    """The row's verdict (DLC rows carry none: judge them the same way)."""
    from ..recommender import Verdict, verdict
    v = getattr(r, "verdict", None)
    return (v if isinstance(v, Verdict) else verdict(r.item.cut, r.hist)).kind


# A message has to be worth reading: only HOT prices, plus your own targets and a wishlist record running out.
# GREAT prices come back every few weeks, so they never ping you on their own.


def detect(digest, dlc_rows, n, now: float | None = None) -> list[Event]:
    now = now or time.time()
    out: list[Event] = []
    for r in digest.wish:
        tgt = r.extras.get("target")
        if tgt and tgt.get("hit"):
            out.append(Event("wish_target", r.item.appid, r.item.final_cents, "", Card.from_rec(r, "wish_target")))
        elif _kind(r) == "hot":
            out.append(Event("wish_lowest", r.item.appid, r.item.final_cents, "", Card.from_rec(r, "wish_lowest")))
        if r.item.ends_at and 0 < r.item.ends_at - now < 26 * 3600 and _kind(r) in ("hot", "great"):
            out.append(Event("ending", r.item.appid, r.item.final_cents, str(r.item.ends_at),
                             Card.from_rec(r, "ending")))
    strong = [r for r in digest.picks[:25] if r.score >= n.min_score and _kind(r) == "hot"]
    for r in strong[:5]:
        out.append(Event("pick_strong", r.item.appid, r.item.final_cents, "", Card.from_rec(r, "pick_strong")))
    for row in dlc_rows or []:
        if row.owner_kind == "you" and row.hours >= 10 and row.hist and _kind(row) == "hot":
            out.append(Event("dlc_lowest", row.item.appid, row.item.final_cents, "", Card.from_dlc(row)))
    if digest.sale_now:
        s = digest.sale_now
        top = digest.wish[:3] + digest.picks[:5]
        card = Card(0, "sale_start", sale_name(s.name), "", "", 0, "", int(dt.datetime.combine(
            s.end, dt.time(19)).timestamp()), None, 0, " · ".join(r.item.name for r in top), 0,
            "https://store.steampowered.com/specials", top[0].item.cover if top else "")
        out.append(Event("sale_start", 0, 0, f"{s.name}:{s.start.isoformat()}", card))
    wanted = set(n.events)
    out = [e for e in out if e.kind in wanted]
    out.sort(key=lambda e: ORDER.index(e.kind))
    seen, uniq = set(), []
    for e in out:                                   # one event per game: the most important kind wins
        if e.appid and e.appid in seen and e.kind != "ending":
            continue
        seen.add(e.appid)
        uniq.append(e)
    return uniq


def fresh(events: list[Event], profile: str, now: float | None = None) -> list[Event]:
    """Drop events already announced at the same (or lower) price recently."""
    now = now or time.time()
    out = []
    for e in events:
        row = db().execute("SELECT price_cents, extra, at FROM notified WHERE profile=? AND appid=? AND kind=?",
                           (profile, e.appid, e.kind))
        if row:
            price, extra, at = row[0]
            cheaper = e.price_cents < price
            if not cheaper and extra == e.extra and now - at < RENOTIFY_AFTER:
                continue
        out.append(e)
    return out


def mark(events: list[Event], profile: str, now: float | None = None) -> None:
    now = int(now or time.time())
    for e in events:
        db().execute("INSERT OR REPLACE INTO notified VALUES (?,?,?,?,?,?)",
                     (profile, e.appid, e.kind, e.price_cents, e.extra, now))


# --------------------------------------------------------------------------- digest queue

def enqueue(events: list[Event], profile: str, now: float | None = None) -> None:
    now = int(now or time.time())
    for e in events:
        db().execute("INSERT OR REPLACE INTO pending VALUES (?,?,?,?,?)",
                     (profile, e.appid, e.kind, json.dumps(e.card.to_json(), ensure_ascii=False), now))


def take_pending(profile: str) -> list[Card]:
    rows = db().execute("SELECT kind, payload FROM pending WHERE profile=? ORDER BY at", (profile,))
    db().execute("DELETE FROM pending WHERE profile=?", (profile,))
    cards = [Card.from_json(json.loads(p)) for _, p in rows]
    cards.sort(key=lambda c: ORDER.index(c.kind) if c.kind in ORDER else 99)
    return cards


def pending_count(profile: str) -> int:
    return db().execute("SELECT COUNT(*) FROM pending WHERE profile=?", (profile,))[0][0]


# --------------------------------------------------------------------------- timing

def _hm(s: str) -> dt.time | None:
    try:
        h, m = s.strip().split(":")
        return dt.time(int(h) % 24, int(m) % 60)
    except (ValueError, AttributeError):
        return None


def in_quiet(quiet: str, now: dt.datetime) -> bool:
    """'23:00-09:00' (wraps midnight) or '13:00-14:00'."""
    if not quiet or "-" not in quiet:
        return False
    a, b = (_hm(x) for x in quiet.split("-", 1))
    if not a or not b:
        return False
    cur = now.time()
    return a <= cur < b if a < b else (cur >= a or cur < b)


def digest_due(digest_time: str, now: dt.datetime, last_ts: float) -> bool:
    """True once per day after `digest_time` (catches up if the PC was off at that moment)."""
    at = _hm(digest_time) or dt.time(19)
    slot = dt.datetime.combine(now.date(), at)
    if now < slot:
        slot -= dt.timedelta(days=1)
    return last_ts < slot.timestamp() <= now.timestamp()


def digest_title(cards: list[Card]) -> str:
    return t("digest_title", n=len(cards))
