"""Discover — good games on good sales from genres you *don't* usually play (think Spotify's Discover Weekly).

    picks = taste-aligned          discover = acclaimed, well discounted, new to you, but not like what you dropped

Pipeline
  1. Pool       – the regular sale pool + the best-reviewed games on sale + top sellers of a few
                  "frontier" genres you barely touch (rotated every week, so the lanes change).
  2. Novelty    – 1 − (calibrated affinity, closeness to your most-played games, overlap of the
                  game's main genres with your dominant ones). Games close to ones you dropped or
                  ⊘ hid are skipped: new ≠ disliked.
  3. Score      – review quality (Wilson) + deal value + a novelty sweet spot (new, not alien) +
                  confidence (how many people reviewed it); repeats from earlier weeks you ignored fade.
  4. One list   – best first, but varied (no run of the same new genre); each game carries a "bridge":
                  something it shares with your taste, so a recommendation never comes out of nowhere.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math

from .db import Cache
from .recommender import META_TAGS, Profile, Rec, TagSpace, cosine

# Gameplay genres that make good lanes (English Steam tag names), roughly specific → broad.
GENRES = [
    "Metroidvania", "Souls-like", "Roguelike Deckbuilder", "Immersive Sim", "Colony Sim", "City Builder",
    "Automation", "Farming Sim", "Life Sim", "Visual Novel", "Interactive Fiction", "Point & Click", "Detective",
    "Hidden Object", "Escape Room", "Walking Simulator", "Rhythm", "Tower Defense", "Auto Battler",
    "Grand Strategy", "4X", "Turn-Based Tactics", "Tactical RPG", "Real Time Tactics", "RTS", "Wargame",
    "Turn-Based Strategy", "Deckbuilding", "Card Game", "Board Game", "CRPG", "JRPG", "Party-Based RPG",
    "Dungeon Crawler", "Action RPG", "Hack and Slash", "Beat 'em up", "Bullet Hell", "Shoot 'Em Up",
    "Twin Stick Shooter", "Precision Platformer", "Puzzle Platformer", "Platformer", "Stealth", "Fighting",
    "Survival Horror", "Psychological Horror", "Survival", "Base Building", "Sandbox", "Management",
    "Space Sim", "Flight", "Sports", "Racing", "Roguelite", "Roguelike", "Logic", "Puzzle", "Mystery",
    "Hero Shooter", "Battle Royale", "FPS", "Shooter", "Open World", "Exploration", "Arcade", "Strategy",
    "RPG", "Simulation", "Action-Adventure", "Adventure", "Action",
]
_GENRE_SET = set(GENRES)
# Too broad to be a lane on their own: used only when a game has nothing more specific.
BROAD = {"Action", "Adventure", "Action-Adventure", "Exploration", "Open World", "Simulation", "Strategy", "RPG",
         "Arcade", "Shooter", "Puzzle", "Platformer", "Survival", "Sandbox", "Management", "Mystery"}

# Genres worth pulling extra sale pages for when you don't play them (broad enough to have deals).
FRONTIER = [
    "Metroidvania", "Souls-like", "Colony Sim", "City Builder", "Automation", "Farming Sim", "Visual Novel",
    "Point & Click", "Detective", "Rhythm", "Tower Defense", "Grand Strategy", "4X", "Turn-Based Tactics",
    "RTS", "Deckbuilding", "Card Game", "CRPG", "JRPG", "Hack and Slash", "Bullet Hell", "Puzzle Platformer",
    "Stealth", "Fighting", "Survival", "Management", "Puzzle", "Roguelite", "Immersive Sim", "Life Sim",
    "Sports", "Racing", "Platformer", "Space Sim", "Walking Simulator", "Mystery",
]

FAMILIAR_N = 10          # your top tags that count as "what you usually play"
NOVELTY_MIN = 0.42       # below this a game is a regular pick, not a discovery
DISLIKE_MAX = 0.62       # closer than this to a dropped / ⊘ hidden game → skip
MIN_RATING, MIN_REVIEWS, MIN_CUT = 80, 120, 25

_seen = Cache("discover_seen")


def week(today: dt.date | None = None) -> int:
    y, w, _ = (today or dt.date.today()).isocalendar()
    return y * 100 + w


def familiar_tags(profile: Profile, n: int = FAMILIAR_N) -> set[str]:
    return {tag for tag, _ in profile.top_tags(n)}


def known_tags(profile: Profile) -> set[str]:
    """Wider than familiar: your top ~25 tags plus sub-genres of the top ones
    ("Psychological Horror" is not new to a horror fan)."""
    top = familiar_tags(profile)
    words = {tg.lower() for tg in top}
    subs = {g for g in GENRES if g.split()[-1].lower() in words or any(w in words for w in g.lower().split())}
    return familiar_tags(profile, 25) | subs


def frontier(profile: Profile, n: int = 6, today: dt.date | None = None) -> list[str]:
    """Genres you barely play (and don't dislike), a different handful every week."""
    fam = familiar_tags(profile, 14)
    weights = profile.vector
    floor = min(weights.values(), default=0.0)
    cands = [g for g in FRONTIER if g not in fam and not (floor < 0 and weights.get(g, 0.0) < 0.5 * floor)]
    wk = week(today)
    cands.sort(key=lambda g: hashlib.sha1(f"{g}:{wk}".encode()).hexdigest())
    return cands[:n]


def _top_tags(tags: dict[str, float], n: int) -> list[str]:
    return [tg for tg, _ in sorted(tags.items(), key=lambda kv: -kv[1])[:n]]


def lane_of(tags: dict[str, float], familiar: set[str], space: TagSpace) -> str:
    """The genre that makes this game new for you: the most distinctive, strongly voted genre tag you don't play
    (also what keeps the list varied)."""
    if not tags:
        return ""
    top = max(tags.values()) or 1
    best, best_score = "", 0.0
    for tg in _top_tags(tags, 10):
        if tg not in _GENRE_SET or tg in familiar:
            continue
        s = (tags[tg] / top) * math.sqrt(space.idf.get(tg, space.default_idf)) * (0.45 if tg in BROAD else 1.0)
        if s > best_score:
            best, best_score = tg, s
    return best                  # "" = no clear new genre: the game still counts, it just doesn't claim one


def bridge_of(tags: dict[str, float], profile: Profile, skip: str, space: TagSpace | None = None) -> str:
    """Something this game shares with what you love — the reason it isn't a random suggestion.
    Distinctive links ("atmospheric", "story rich") beat generic ones ("action")."""
    liked = {tg: w for tg, w in profile.top_tags(30)}
    idf = (lambda tg: space.idf.get(tg, space.default_idf)) if space else (lambda tg: 1.0)
    shared = [(liked[tg] * idf(tg) * (0.5 if tg in BROAD else 1.0), tg) for tg in _top_tags(tags, 12)
              if tg in liked and tg != skip]
    return max(shared)[1] if shared else ""


def novelty(rec: Rec, familiar: set[str], known: set[str] | None = None) -> float:
    main = [tg for tg in _top_tags(rec.item.tags, 5) if tg not in META_TAGS][:3]
    known = known or set()
    overlap = sum(1.0 if tg in familiar else 0.5 if tg in known else 0.0 for tg in main) / max(1, len(main))
    return max(0.0, min(1.0, 1 - (0.45 * rec.affinity + 0.30 * rec.similarity + 0.25 * overlap)))


def dislike(vec: dict[str, float], profile: Profile) -> float:
    return max((cosine(vec, s.vec) for s in profile.signals if s.weight < 0 and s.vec), default=0.0)


def gem(rec: Rec) -> bool:
    """Loved by nearly everyone who played it, but few did."""
    i = rec.item
    return (i.review_pct or 0) >= 93 and 150 <= i.review_count <= 6000


def candidates(recs: list[Rec], profile: Profile, space: TagSpace, interest: dict[int, int] | None = None,
               today: dt.date | None = None) -> list[Rec]:
    """Discovery copies of already calibrated taste recs (same pool, different question)."""
    from dataclasses import replace

    familiar, known = familiar_tags(profile), known_tags(profile)
    seen = _seen.get(_profile_key()) or {}
    wk = week(today)
    out = []
    for r in recs:
        i = r.item
        if (i.review_pct or 0) < MIN_RATING or i.review_count < MIN_REVIEWS or i.cut < MIN_CUT:
            continue
        nov = novelty(r, familiar, known)
        if nov < NOVELTY_MIN:
            continue
        vec = space.vec(i.tags)
        if dislike(vec, profile) > DISLIKE_MAX:
            continue
        lane = lane_of(i.tags, known, space)
        bridge = bridge_of(i.tags, profile, lane, space)
        extras = dict(r.extras, new=lane, bridge=bridge)
        d = replace(r, mode="discover", novelty=nov, lane=lane, why=explain(lane, bridge),
                    extras=extras)
        if gem(d):
            d.extras["gem"] = True
        first = seen.get(str(i.appid))
        if first and first < wk and not (interest or {}).get(i.appid):
            d.penalty = max(0.6, 0.88 ** _weeks_between(first, wk))     # shown before, you passed: let it fade
        d.rescore()
        out.append(d)
    return out


def explain(new: str, bridge: str) -> str:
    """'new for you: metroidvania · from your taste: atmospheric'."""
    from .i18n import t
    from .steam import local_tag
    parts = [t("why_new", tag=local_tag(new).lower())] if new else []
    if bridge:
        parts.append(t("why_bridge", tag=local_tag(bridge).lower()))
    return " · ".join(parts)


def _weeks_between(a: int, b: int) -> int:
    da = dt.date.fromisocalendar(a // 100, a % 100, 1)
    db_ = dt.date.fromisocalendar(b // 100, b % 100, 1)
    return max(1, (db_ - da).days // 7)


def arrange(recs: list[Rec], window: int = 8, spacing: int = 3) -> list[Rec]:
    """One list, best first, but varied: the next slot goes to the best game (among the next few)
    whose new genre didn't appear in the last `spacing` rows — no three fighting games in a row.
    One game per franchise up top; a sequel waits at the end."""
    franchises: set[str] = set()
    pool, repeats = [], []
    for r in sorted(recs, key=lambda r: -r.score):
        fr = r.item.franchises[0] if r.item.franchises else None
        if fr and fr in franchises:
            repeats.append(r)
            continue
        if fr:
            franchises.add(fr)
        pool.append(r)
    out: list[Rec] = []
    while pool:
        recent = {x.lane for x in out[-spacing:]}
        pick = next((r for r in pool[:window] if r.lane not in recent), pool[0])
        pool.remove(pick)
        out.append(pick)
    for r in out + repeats:
        r.why = explain(r.lane, r.extras.get("bridge", ""))
    return out + repeats


def remember(recs: list[Rec], today: dt.date | None = None, n: int = 40) -> None:
    """Note what was shown this week, so next week brings different games."""
    key = _profile_key()
    seen = _seen.get(key) or {}
    wk = week(today)
    for r in recs[:n]:
        seen.setdefault(str(r.item.appid), wk)
    if len(seen) > 3000:
        seen = dict(sorted(seen.items(), key=lambda kv: kv[1])[-3000:])
    _seen.set(key, seen)


def _profile_key() -> str:
    from . import config
    return getattr(config, "cfg", None) and config.cfg.profile_name or "main"
