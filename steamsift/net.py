"""HTTP helpers: pooled session, retries, optional SSH fallback for store blocks."""
from __future__ import annotations

import datetime as dt
from email.utils import parsedate_to_datetime
import json
import subprocess
import time
from typing import Any
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

from . import config

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

MAX_WAIT = 5.0                      # seconds we are willing to sleep on one 429
_hold: dict[str, float] = {}        # host -> unix time until which we do not call it

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"})
SESSION.mount("https://", HTTPAdapter(pool_connections=16, pool_maxsize=16))


def _remote_fetch(url: str, timeout: int) -> bytes | None:
    """Fetch through the home desktop over SSH when this IP gets blocked."""
    st = getattr(config, "cfg", None)
    host = st.settings.remote_fetch_host if st else ""
    script = st.settings.remote_fetch_script if st else ""
    if not host or not script:
        return None
    try:
        cmd = ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", host, f'python {script} "{url}"']
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def request_json(
    url: str,
    params: dict | None = None,
    payload: Any = None,
    timeout: int = 15,
    retries: int = 2,
    remote_fallback: bool = False,
) -> Any:
    """GET (or POST when payload is given) and decode JSON. Returns None on failure.

    A 429 waits at most MAX_WAIT once; a longer Retry-After puts the host on hold, and calls to it
    return None at once until the hold ends (a rate-limited API must never freeze the app)."""
    host = urlsplit(url).netloc
    if _hold.get(host, 0) > time.time():
        return None
    retried_429 = False
    for attempt in range(retries + 1):
        try:
            if payload is None:
                resp = SESSION.get(url, params=params, timeout=timeout)
            else:
                resp = SESSION.post(url, params=params, json=payload, timeout=timeout)
        except requests.RequestException:
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
                continue
            return None

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                return None
        if resp.status_code in (403, 429) and remote_fallback and payload is None:
            raw = _remote_fetch(resp.url, timeout)
            if raw:
                try:
                    return json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:
                    return None
        if resp.status_code == 429:
            value = resp.headers.get("Retry-After", "1")
            try:
                delay = float(value)
            except ValueError:
                try:
                    delay = (parsedate_to_datetime(value) - dt.datetime.now(dt.timezone.utc)).total_seconds()
                except (ValueError, TypeError):
                    delay = 1.0
            if delay > MAX_WAIT:
                _hold[host] = time.time() + delay
                return None
            if attempt < retries and not retried_429:
                retried_429 = True
                time.sleep(max(0, delay))
                continue
            return None
        if resp.status_code in (500, 502, 503, 504) and attempt < retries:
            time.sleep(1.0 * (attempt + 1))
            continue
        return None
    return None
