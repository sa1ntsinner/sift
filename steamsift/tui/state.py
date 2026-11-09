"""Last usable screen, stored as versioned JSON in the existing SQLite database."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field, fields, is_dataclass, replace

from .. import config
from ..calendar import Event
from ..db import Cache, db
from ..engine import Digest, DlcRow
from ..itad import Bundle, Elsewhere, History
from ..recommender import Rec, Verdict
from ..steam import Item, Library

REFRESH_AFTER = 15 * 60
_snapshots = Cache("tui_snapshot_v4")   # v3: pick order (0.4)


@dataclass
class SavedContext:
    lib: Library
    family_shared: set[int]
    family_unshared: set[int]
    hidden: dict


@dataclass
class Data:
    ctx: object
    digest: Digest
    dlc: list = field(default_factory=list)
    saved_at: float = 0
    dlc_at: float = 0
    complete: bool = True
    pending: int = 0        # games whose price history is still to come (ITAD's call budget): the next run goes on


_TYPES = {cls.__name__: cls for cls in
          (SavedContext, Data, Digest, DlcRow, Event, Item, Library, Rec, Verdict, History, Bundle, Elsewhere)}


def _encode(value):
    if is_dataclass(value):
        return {"_type": type(value).__name__, "value": {f.name: getattr(value, f.name) for f in fields(value)}}
    if isinstance(value, dt.date):
        return {"_type": "date", "value": value.isoformat()}
    if isinstance(value, set):
        return {"_type": "set", "value": sorted(value)}
    raise TypeError(f"Cannot save {type(value).__name__}")


def _decode(value):
    kind = value.get("_type")
    if kind is None:
        return value
    body = value["value"]
    if kind == "date":
        return dt.date.fromisoformat(body)
    if kind == "set":
        return set(body)
    cls = _TYPES[kind]             # only these data classes can be loaded; never import code from a snapshot
    if cls is Library:
        for key in ("my_games", "family_games"):
            body[key] = {int(k): v for k, v in body[key].items()}
    if cls is SavedContext:
        body["hidden"] = {int(k): v for k, v in body["hidden"].items()}
    if cls is History:
        body["points"] = [tuple(p) for p in body["points"]]
    return cls(**body)


def _key() -> str:
    c = config.cfg
    identity = [c.profile_name, c.steam_id, c.country, c.lang, c.family,
                c.profile.seeds, c.profile.to_dict()["filters"]]
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def load_snapshot() -> Data | None:
    raw = _snapshots.get(_key())
    if raw is None:
        return None
    try:
        data = json.loads(raw, object_hook=_decode)
        if not isinstance(data, Data) or not isinstance(data.ctx, SavedContext) or not isinstance(data.digest, Digest):
            return None
        if not isinstance(data.saved_at, (int, float)) or not isinstance(data.dlc_at, (int, float)):
            return None
        for rows in (data.digest.picks, data.digest.wish, data.digest.discover, data.digest.waiting, data.dlc):
            if not isinstance(rows, list) or any(not isinstance(r, (Rec, DlcRow)) or
                                                 not isinstance(r.item, Item) for r in rows):
                return None
        return data
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def save_snapshot(data: Data) -> None:
    ctx = data.ctx
    saved = replace(data, ctx=SavedContext(ctx.lib, ctx.family_shared, ctx.family_unshared, ctx.hidden))
    _snapshots.set(_key(), json.dumps(saved, default=_encode, ensure_ascii=False, separators=(",", ":")))
    db().flush()
