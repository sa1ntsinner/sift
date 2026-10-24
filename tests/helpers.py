"""Offline builders: games, libraries and a real engine.Context without touching the network."""
from __future__ import annotations

import datetime as dt
import time

from steamsift import calendar, engine
from steamsift.engine import Context
from steamsift.itad import History
from steamsift.steam import Item, Library

RACING = {"Racing": 1000, "Automobile Sim": 800, "Simulation": 600, "Driving": 500, "Realistic": 300}
HORROR = {"Horror": 1000, "Survival Horror": 800, "Atmospheric": 600, "Dark": 400, "Singleplayer": 300}
PUZZLE = {"Puzzle": 1000, "Casual": 700, "2D": 500, "Relaxing": 400, "Cute": 300}
SHOOTER = {"FPS": 1000, "Shooter": 900, "Action": 700, "Multiplayer": 500, "PvP": 400}


def item(appid: int, name: str, tags: dict | None = None, cut: int = 50, price: int = 999, **kw) -> Item:
    base = dict(appid=appid, name=name, tags=dict(tags or RACING), review_pct=92, review_count=8000, cut=cut,
                final_cents=price, orig_cents=price * 2 if cut else price, final_fmt=f"${price / 100:.2f}",
                orig_fmt=f"${price * 2 / 100:.2f}", ends_at=int(time.time()) + 5 * 86400, deck=3,
                platforms=["windows"], languages={"0": 7, "8": 3})
    base.update(kw)
    return Item(**base)


def library(played: dict[int, tuple[str, float]] | None = None, wishlist: list[int] | None = None,
            family: dict[int, dict] | None = None) -> Library:
    now = int(time.time())
    games = {a: {"appid": a, "name": n, "playtime_forever": int(h * 60), "playtime_2weeks": 0,
                 "rtime_last_played": now - 10 * 86400} for a, (n, h) in (played or {}).items()}
    return Library(user_name="tester", steam_id="76561198012345678", my_games=games, family_name="Fam",
                   family_source="client", family_members=[], family_games=family or {},
                   wishlist=[{"appid": a, "priority": 0, "date_added": now} for a in (wishlist or [])])


def make_ctx(lib: Library, meta: dict[int, Item], wish: dict[int, Item] | None = None,
             candidates: dict[int, Item] | None = None, hidden: dict | None = None, seeds: list[int] | None = None,
             interest: dict | None = None, unshared: set[int] | None = None) -> Context:
    ctx = object.__new__(Context)
    ctx.lib = lib
    ctx.hidden = hidden or {}
    ctx.seeds = seeds or []
    ctx.interest = interest or {}
    ctx.family_unshared = set(unshared or set())
    ctx.family_shared = set(lib.family_games) - ctx.family_unshared
    ctx.meta = dict(meta)
    ctx.wish_items = dict(wish or {})
    ctx.candidates = dict(candidates or {})
    ctx.rebuild()
    return ctx


def racing_fan() -> tuple[Library, dict[int, Item]]:
    """A player with ~200h of sim racing and a little horror."""
    meta = {1: item(1, "Assetto Corsa", RACING), 2: item(2, "Le Mans Ultimate", RACING),
            3: item(3, "Resident Evil 0", HORROR)}
    lib = library({1: ("Assetto Corsa", 120), 2: ("Le Mans Ultimate", 90), 3: ("Resident Evil 0", 6)})
    return lib, meta


def offline_digest(monkeypatch, events: list[calendar.Event] | None = None, accounts: dict | None = None,
                   history: dict | None = None) -> None:
    """Make build_digest/enrich deterministic and offline."""
    monkeypatch.setattr(engine.itad, "bundles", lambda ids: {})
    monkeypatch.setattr(engine.calendar, "events", lambda: list(events or []))
    monkeypatch.setattr(engine, "third_party_accounts", lambda ids: {a: v for a, v in (accounts or {}).items()
                                                                      if a in ids})
    monkeypatch.setattr(engine.itad, "history", lambda ids, deep=None: {
        a: (v if isinstance(v, History) else History(v)) for a, v in (history or {}).items() if a in ids
    })


def sale(name: str, start: dt.date, days: int = 14) -> calendar.Event:
    return calendar.Event(name, "sale", start, start + dt.timedelta(days=days))
