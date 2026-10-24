"""Per-profile user choices that must survive cache wipes: hidden ("don't recommend") games."""
from __future__ import annotations

import json
import re
import time

from . import config
from .config import CONFIG_DIR
from .db import db

# reason "taste": not my kind of game -> excluded AND used as a light negative taste signal
# reason "owned": have it elsewhere / not now -> excluded only
REASONS = ("taste", "owned")

_LEGACY_HIDDEN = CONFIG_DIR / "hidden.json"


def _profile() -> str:
    return config.cfg.profile_name


def _migrate_legacy() -> None:
    if not _LEGACY_HIDDEN.exists():
        return
    try:
        raw = json.loads(_LEGACY_HIDDEN.read_text(encoding="utf-8"))
        for k, v in raw.items():
            db().execute("INSERT OR IGNORE INTO hidden VALUES (?,?,?,?,?)",
                         (_profile(), int(k), v.get("name", ""), v.get("reason", "taste"), int(v.get("at", 0))))
        _LEGACY_HIDDEN.rename(_LEGACY_HIDDEN.with_suffix(".json.migrated"))
    except (OSError, ValueError):
        pass


def load_hidden() -> dict[int, dict]:
    _migrate_legacy()
    rows = db().execute("SELECT appid, name, reason, at FROM hidden WHERE profile=? ORDER BY at", (_profile(),))
    return {a: {"name": n, "reason": r, "at": at} for a, n, r, at in rows}


def hide(appid: int, name: str, reason: str = "taste") -> None:
    db().execute("INSERT OR REPLACE INTO hidden VALUES (?,?,?,?,?)",
                 (_profile(), appid, name, reason if reason in REASONS else "taste", int(time.time())))


def unhide(appid: int) -> bool:
    before = len(load_hidden())
    db().execute("DELETE FROM hidden WHERE profile=? AND appid=?", (_profile(), appid))
    return len(load_hidden()) < before


def clear_hidden() -> int:
    n = len(load_hidden())
    db().execute("DELETE FROM hidden WHERE profile=?", (_profile(),))
    return n


_EDITION_RE = re.compile(
    r"\b(game of the year|goty|definitive|complete|deluxe|ultimate|gold|enhanced|remastered|remaster|"
    r"director'?s cut|anniversary|standard|premium|digital|legendary|special|collector'?s)\b( edition)?|\bedition\b"
)


def normalize_title(title: str) -> str:
    """Edition-insensitive title key: 'Sekiro™ - GOTY Edition' == 'Sekiro'."""
    t = title.lower()
    t = re.sub(r"[™®©]", "", t)
    t = _EDITION_RE.sub(" ", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# --------------------------------------------------------------------------- target prices

def set_target(appid: int, name: str, price_cents: int | None) -> None:
    """price_cents None = "tell me when it hits its all-time low"."""
    db().execute("INSERT OR REPLACE INTO targets VALUES (?,?,?,?,?)",
                 (_profile(), appid, name, price_cents, int(time.time())))


def remove_target(appid: int) -> bool:
    before = len(targets())
    db().execute("DELETE FROM targets WHERE profile=? AND appid=?", (_profile(), appid))
    return len(targets()) < before


def targets() -> dict[int, dict]:
    rows = db().execute("SELECT appid, name, price_cents, at FROM targets WHERE profile=? ORDER BY at",
                        (_profile(),))
    return {a: {"name": n, "price_cents": p, "at": at} for a, n, p, at in rows}


# --------------------------------------------------------------------------- feedback (learning)

FEEDBACK_WINDOW = 120 * 86400


def log_feedback(appid: int, action: str) -> None:
    """action: open (went to the store page) | info (asked for details)."""
    db().execute("INSERT INTO feedback VALUES (?,?,?,?)", (_profile(), int(appid), action, int(time.time())))


def interest() -> dict[int, int]:
    """appid -> how often you showed interest recently (store opens count double)."""
    rows = db().execute("SELECT appid, action FROM feedback WHERE profile=? AND at>?",
                        (_profile(), int(time.time()) - FEEDBACK_WINDOW))
    out: dict[int, int] = {}
    for appid, action in rows:
        out[appid] = out.get(appid, 0) + (2 if action == "open" else 1)
    return out
