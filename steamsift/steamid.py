"""Turn whatever a user pastes into a SteamID64.

Accepted: 7656119…, steamcommunity.com/profiles/<id64|[U:1:n]>, steamcommunity.com/id/<vanity>,
bare vanity names, STEAM_0:Y:Z, [U:1:n], friend codes (32-bit account id),
quick-invite links s.team/p/xxxx-xxxx and steamcommunity.com/user/xxxx-xxxx.
"""
from __future__ import annotations

import re

BASE = 76561197960265728
_INVITE_ALPHABET = "bcdfghjkmnpqrtvw"   # Steam quick-invite codes: hex digits remapped


def from_account_id(account_id: int) -> str:
    return str(BASE + int(account_id))


def to_account_id(steam_id64: str | int) -> int:
    return int(steam_id64) - BASE


def decode_invite(code: str) -> int | None:
    code = code.strip().lower().replace("-", "")
    if not code or any(c not in _INVITE_ALPHABET for c in code):
        return None
    return int("".join("0123456789abcdef"[_INVITE_ALPHABET.index(c)] for c in code), 16)


def encode_invite(account_id: int) -> str:
    raw = "".join(_INVITE_ALPHABET["0123456789abcdef".index(c)] for c in f"{account_id:x}")
    half = len(raw) // 2
    return f"{raw[:half]}-{raw[half:]}" if len(raw) > 4 else raw


def parse(text: str) -> tuple[str, str] | None:
    """('id64', '7656…') when the input is self-contained, ('vanity', name) when it needs the API."""
    s = text.strip().strip("<>").strip()
    if not s:
        return None
    s = re.sub(r"^(https?://)?(www\.)?", "", s, flags=re.I).rstrip("/")

    m = re.match(r"(steamcommunity\.com/profiles/)?(7656119\d{10})(/.*)?$", s, re.I)
    if m:
        return "id64", m.group(2)
    m = re.match(r"(?:steamcommunity\.com/profiles/)?\[?U:1:(\d+)\]?(/.*)?$", s, re.I)
    if m:
        return "id64", from_account_id(int(m.group(1)))
    m = re.match(r"STEAM_[0-5]:([01]):(\d+)$", s, re.I)
    if m:
        return "id64", from_account_id(int(m.group(2)) * 2 + int(m.group(1)))
    m = re.match(r"(?:s\.team/p/|steamcommunity\.com/user/)([a-z-]+)(/.*)?$", s, re.I)
    if m:
        acc = decode_invite(m.group(1))
        return ("id64", from_account_id(acc)) if acc else None
    m = re.match(r"steamcommunity\.com/id/([^/?#]+)", s, re.I)
    if m:
        return "vanity", m.group(1)
    if s.isdigit() and 0 < int(s) < 2 ** 32:
        return "id64", from_account_id(int(s))       # friend code
    if re.fullmatch(r"[A-Za-z0-9_-]{2,32}", s):
        return "vanity", s
    return None


def resolve(text: str, api_key: str) -> str | None:
    parsed = parse(text)
    if not parsed:
        return None
    kind, value = parsed
    if kind == "id64":
        return value
    if not api_key:
        return None
    from .net import request_json
    data = request_json("https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/",
                        params={"key": api_key, "vanityurl": value}) or {}
    resp = data.get("response", {}) if isinstance(data, dict) else {}
    return resp.get("steamid") if resp.get("success") == 1 else None
