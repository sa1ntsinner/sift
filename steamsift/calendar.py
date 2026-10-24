"""Steam sale calendar, parsed from Valve's public partner page (seasonal sales + themed fests).

Used for "wait — the Summer Sale starts in 9 days" hints and for fests matching your taste.
"""
from __future__ import annotations

import datetime as dt
import html as htmllib
import re
from dataclasses import dataclass, field

from .db import DAY, Cache
from .net import SESSION

URL = "https://partner.steamgames.com/doc/marketing/upcoming_events"
_cache = Cache("calendar")

# Themed fests -> the Steam tags whose games usually get discounted during them.
FEST_TAGS: dict[str, list[str]] = {
    "Racing Fest": ["Racing", "Driving", "Automobile Sim"],
    "Steam Scream": ["Horror", "Psychological Horror", "Survival Horror"],
    "Real-Time Strategy Fest": ["RTS", "Strategy"],
    "Fighting Fest": ["Fighting", "2D Fighter", "3D Fighter", "Beat 'em up"],
    "Rhythm Fest": ["Rhythm", "Music"],
    "Couch Co-Op Fest": ["Local Co-Op", "Local Multiplayer"],
    "Cooking Fest": ["Cooking"],
    "Shop Keeper Fest": ["Management", "Economy"],
    "Dinos vs. Robots Fest": ["Dinosaurs", "Robots", "Mechs"],
    "Witch Fest": ["Magic", "Witch"],
    "Mountaineering Fest": ["Climbing"],
    "Medieval Fest": ["Medieval"],
    "Auto-Battler RPG Fest": ["Auto Battler"],
    "Survival Fest": ["Survival"],
    "Open World Survival Craft Fest": ["Open World Survival Craft"],
    "Simulation Fest": ["Simulation"],
    "Puzzle Fest": ["Puzzle"],
    "Sports Fest": ["Sports"],
    "Strategy Fest": ["Strategy"],
}

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


@dataclass
class Event:
    name: str
    kind: str                  # "sale" (seasonal, store-wide) | "fest" (themed)
    start: dt.date
    end: dt.date
    tags: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"name": self.name, "kind": self.kind, "start": self.start.isoformat(),
                "end": self.end.isoformat(), "tags": self.tags}

    @classmethod
    def from_json(cls, d: dict) -> "Event":
        return cls(d["name"], d["kind"], dt.date.fromisoformat(d["start"]), dt.date.fromisoformat(d["end"]),
                   d.get("tags", []))


def _date(text: str) -> dt.date | None:
    m = re.match(r"(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})", text.strip())
    if not m:
        return None
    month = _MONTHS.get(m.group(2)[:3].lower())
    return dt.date(int(m.group(3)), month, int(m.group(1))) if month else None


def _plain(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse(page: str) -> list[Event]:
    events: list[Event] = []
    text = _plain(page)
    for m in re.finditer(r"(Spring|Summer|Autumn|Winter) Sale (\d{4})\s*\|?\s*(\d{1,2} [A-Za-z]+,? \d{4})\s*[-–]\s*"
                         r"(\d{1,2} [A-Za-z]+,? \d{4})", text):
        start, end = _date(m.group(3)), _date(m.group(4))
        if start and end:
            events.append(Event(f"Steam {m.group(1)} Sale", "sale", start, end))

    # Themed fests live in tables that follow "<year> Fests" headings.
    year = None
    for m in re.finditer(r"(20\d\d) Fests|<tr[^>]*>(.*?)</tr>", page, re.S):
        if m.group(1):
            year = int(m.group(1))
            continue
        if year is None:
            continue
        cells = [_plain(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", m.group(2), re.S)]
        if len(cells) < 2:
            continue
        d = re.match(r"([A-Za-z]{3})[a-z]*\.? (\d{1,2})\s*[-–]?\s*(?:([A-Za-z]{3})[a-z]*\.? )?(\d{1,2})$", cells[0])
        if not d:
            continue
        m1, d1 = _MONTHS.get(d.group(1).lower()), int(d.group(2))
        m2, d2 = _MONTHS.get((d.group(3) or d.group(1)).lower()), int(d.group(4))
        if not m1 or not m2:
            continue
        start = dt.date(year, m1, d1)
        end = dt.date(year + (1 if m2 < m1 else 0), m2, d2)
        name = cells[1]
        tags = next((v for k, v in FEST_TAGS.items() if k.lower() in name.lower()), [])
        events.append(Event(name, "fest", start, end, tags))

    uniq = {(e.name, e.start): e for e in events}
    return sorted(uniq.values(), key=lambda e: e.start)


def events() -> list[Event]:
    cached = _cache.get("events", 7 * DAY)
    if cached is not None:
        return [Event.from_json(e) for e in cached]
    try:
        r = SESSION.get(URL, timeout=15)
        evs = parse(r.text) if r.status_code == 200 else []
    except Exception:  # noqa: BLE001 - the calendar is a nice-to-have
        evs = []
    if evs:
        _cache.set("events", [e.to_json() for e in evs])
    return evs


def current_sale(today: dt.date | None = None, evs: list[Event] | None = None) -> Event | None:
    today = today or dt.date.today()
    return next((e for e in (evs if evs is not None else events())
                 if e.kind == "sale" and e.start <= today <= e.end), None)


def next_sale(today: dt.date | None = None, within_days: int = 45, evs: list[Event] | None = None) -> Event | None:
    today = today or dt.date.today()
    return next((e for e in (evs if evs is not None else events())
                 if e.kind == "sale" and today < e.start <= today + dt.timedelta(days=within_days)), None)


def fests_for(taste_tags: list[str], today: dt.date | None = None, within_days: int = 60,
              evs: list[Event] | None = None) -> list[Event]:
    """Upcoming or running themed fests whose tags overlap your strongest taste tags."""
    today = today or dt.date.today()
    want = {t.lower() for t in taste_tags}
    return [e for e in (evs if evs is not None else events())
            if e.kind == "fest" and e.end >= today and e.start <= today + dt.timedelta(days=within_days)
            and want & {t.lower() for t in e.tags}]
