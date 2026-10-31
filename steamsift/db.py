"""Local SQLite store: cache namespaces, own price history, hidden games.

Cache namespaces are loaded lazily into memory and checkpointed in transactions,
so hundreds of lookups per run cost nothing.
"""
from __future__ import annotations

import atexit
import json
import sqlite3
import threading
import time
from typing import Any

from .config import STATE_DIR

DB_FILE = STATE_DIR / "sift.db"
SCHEMA_VERSION = 1

HOUR = 3600
DAY = 86400

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    ns TEXT NOT NULL, key TEXT NOT NULL, ts REAL NOT NULL, value TEXT NOT NULL,
    PRIMARY KEY (ns, key)
);
CREATE TABLE IF NOT EXISTS price_history (
    appid INTEGER NOT NULL, country TEXT NOT NULL, day TEXT NOT NULL,
    final_cents INTEGER NOT NULL, orig_cents INTEGER NOT NULL, cut INTEGER NOT NULL,
    PRIMARY KEY (appid, country, day)
);
CREATE TABLE IF NOT EXISTS targets (
    profile TEXT NOT NULL, appid INTEGER NOT NULL, name TEXT NOT NULL,
    price_cents INTEGER, at INTEGER NOT NULL,          -- NULL price = "tell me at the all-time low"
    PRIMARY KEY (profile, appid)
);
CREATE TABLE IF NOT EXISTS notified (
    profile TEXT NOT NULL, appid INTEGER NOT NULL, kind TEXT NOT NULL,
    price_cents INTEGER NOT NULL, extra TEXT NOT NULL DEFAULT '', at INTEGER NOT NULL,
    PRIMARY KEY (profile, appid, kind)
);
CREATE TABLE IF NOT EXISTS pending (
    profile TEXT NOT NULL, appid INTEGER NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, at INTEGER NOT NULL,
    PRIMARY KEY (profile, appid, kind)
);
CREATE TABLE IF NOT EXISTS feedback (
    profile TEXT NOT NULL, appid INTEGER NOT NULL, action TEXT NOT NULL, at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS hidden (
    profile TEXT NOT NULL, appid INTEGER NOT NULL, name TEXT NOT NULL,
    reason TEXT NOT NULL, at INTEGER NOT NULL,
    PRIMARY KEY (profile, appid)
);
"""


class Database:
    def __init__(self, path=DB_FILE):
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(_SCHEMA)
        self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self._prices: list[tuple] = []

    def execute(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self.lock:
            cur = self.conn.execute(sql, args)
            rows = cur.fetchall()
            self.conn.commit()
            return rows

    def record_price(self, appid: int, country: str, final_cents: int, orig_cents: int, cut: int) -> None:
        with self.lock:
            self._prices.append((appid, country, time.strftime("%Y-%m-%d"), final_cents, orig_cents, cut))

    def flush(self) -> None:
        # Cache reads take their lock before the DB lock; checkpoints must use the same order.
        for c in Cache.all:
            c.flush()
        with self.lock:
            if self._prices:
                with self.conn:
                    self.conn.executemany("INSERT OR REPLACE INTO price_history VALUES (?,?,?,?,?,?)", self._prices)
                self._prices.clear()


_db: Database | None = None
_db_lock = threading.Lock()


def db() -> Database:
    global _db
    with _db_lock:
        if _db is None:
            _db = Database()
        return _db


@atexit.register
def _flush_at_exit() -> None:
    if _db is not None:
        try:
            _db.flush()
        except sqlite3.Error:
            pass


# --------------------------------------------------------------------------- cache

_REFRESH = False
_STALE_OK = False


def set_refresh(value: bool) -> None:
    """When enabled, volatile namespaces ignore stored entries for this run."""
    global _REFRESH
    _REFRESH = value
    if value:
        for cache in Cache.all:
            with cache._lock:
                cache._refreshed.clear()


def refresh_requested() -> bool:
    return _REFRESH


def stale_ok() -> bool:
    """True during the instant first paint: use what is stored, never wait on the network."""
    return _STALE_OK


def set_stale_ok(value: bool) -> None:
    """When enabled, expired entries are still returned (instant first paint; fresh data follows)."""
    global _STALE_OK
    _STALE_OK = value


class Cache:
    all: list["Cache"] = []

    def __init__(self, ns: str, volatile: bool = False):
        self.ns = ns
        self.volatile = volatile
        self._data: dict[str, tuple[float, Any]] | None = None
        self._dirty: set[str] = set()
        self._refreshed: set[str] = set()
        self._lock = threading.Lock()
        Cache.all.append(self)

    def _load(self) -> dict[str, tuple[float, Any]]:
        if self._data is None:
            rows = db().execute("SELECT key, ts, value FROM kv WHERE ns=?", (self.ns,))
            data = {}
            for k, ts, v in rows:
                try:
                    data[k] = (ts, json.loads(v))
                except ValueError:
                    continue
            self._data = data
        return self._data

    def get(self, key: Any, ttl: float | None = None) -> Any:
        with self._lock:
            if self.volatile and _REFRESH and not _STALE_OK and str(key) not in self._refreshed:
                return None
            entry = self._load().get(str(key))
        if entry is None:
            return None
        ts, value = entry
        if ttl is not None and not _STALE_OK and time.time() - ts > ttl:
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        if _STALE_OK:
            return
        with self._lock:
            self._load()[str(key)] = (time.time(), value)
            self._dirty.add(str(key))
            self._refreshed.add(str(key))

    def flush(self) -> None:
        with self._lock:
            if not self._dirty or self._data is None:
                return
            rows = [(self.ns, k, self._data[k][0], json.dumps(self._data[k][1], ensure_ascii=False,
                                                                separators=(",", ":")))
                    for k in self._dirty if k in self._data]
            store = db()
            with store.lock, store.conn:
                store.conn.executemany("INSERT OR REPLACE INTO kv VALUES (?,?,?,?)", rows)
            self._dirty.clear()


def clear_cache() -> int:
    """Drop every cached API response (keeps price history and hidden games)."""
    for c in Cache.all:
        with c._lock:
            c._data, c._dirty = None, set()
    rows = db().execute("SELECT COUNT(*) FROM kv")
    db().execute("DELETE FROM kv WHERE ns != 'last'")
    db().execute("VACUUM")
    return rows[0][0] if rows else 0


def price_history(appid: int, country: str) -> list[tuple[str, int, int, int]]:
    return db().execute("SELECT day, final_cents, orig_cents, cut FROM price_history "
                        "WHERE appid=? AND country=? ORDER BY day", (appid, country))
