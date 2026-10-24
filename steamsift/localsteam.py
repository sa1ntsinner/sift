"""Read the locally installed Steam client: install roots, KeyValues (VDF) files, Steam Family."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .steamid import from_account_id, to_account_id


def steam_roots() -> list[Path]:
    """Every plausible Steam install, most authoritative first (registry, then known paths)."""
    cands: list[Path] = []
    home = Path.home()
    if sys.platform == "win32":
        try:
            import winreg
            for hive, key, val in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                   (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                                   (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        cands.append(Path(winreg.QueryValueEx(k, val)[0]))
                except OSError:
                    pass
        except ImportError:
            pass
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        cands += [Path(pf86) / "Steam", Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Steam"]
    elif sys.platform == "darwin":
        cands.append(home / "Library" / "Application Support" / "Steam")
    else:
        cands += [
            home / ".steam" / "steam",
            home / ".local" / "share" / "Steam",
            home / ".steam" / "root",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".steam" / "steam",       # Flatpak
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
            home / "snap" / "steam" / "common" / ".local" / "share" / "Steam",            # Snap
        ]
    out, seen = [], set()
    for p in cands:
        try:
            rp = p.resolve()
        except OSError:
            continue
        if rp not in seen and (p / "userdata").is_dir():
            seen.add(rp)
            out.append(p)
    return out


# --------------------------------------------------------------------------- VDF (text KeyValues)

def parse_vdf(text: str) -> dict:
    """Minimal KeyValues parser: quoted/unquoted tokens, nested blocks, // comments, escapes."""
    i, n = 0, len(text)
    OPEN, CLOSE = object(), object()
    toks: list = []
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "/" and text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
        elif c == "{":
            toks.append(OPEN)
            i += 1
        elif c == "}":
            toks.append(CLOSE)
            i += 1
        elif c == '"':
            i += 1
            buf = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    nxt = text[i + 1]
                    buf.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(nxt, nxt))
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            toks.append("".join(buf))
            i += 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n{}"':
                j += 1
            toks.append(text[i:j])
            i = j

    def block(pos: int) -> tuple[dict, int]:
        out: dict = {}
        while pos < len(toks):
            t = toks[pos]
            if t is CLOSE:
                return out, pos + 1
            if t is OPEN:          # malformed: stray brace
                pos += 1
                continue
            key = t
            pos += 1
            if pos >= len(toks):
                break
            if toks[pos] is OPEN:
                val, pos = block(pos + 1)
            elif toks[pos] is CLOSE:
                break
            else:
                val, pos = toks[pos], pos + 1
            out[key] = val
        return out, pos

    return block(0)[0]


def ci_get(d: dict, *path: str):
    """Case-insensitive nested lookup (VDF keys vary in case between Steam versions)."""
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        low = key.lower()
        cur = next((v for k, v in cur.items() if k.lower() == low), None)
    return cur


# --------------------------------------------------------------------------- family

def localconfig_path(steam_id64: str) -> Path | None:
    """This user's localconfig.vdf, never another account's on the same PC."""
    try:
        acc = str(to_account_id(steam_id64))
    except (TypeError, ValueError):
        return None
    for root in steam_roots():
        p = root / "userdata" / acc / "config" / "localconfig.vdf"
        if p.is_file():
            return p
    return None


def family_from_client(steam_id64: str) -> dict:
    """{'name': str, 'member_steam_ids': [...]} read from the local Steam client, or {}."""
    path = localconfig_path(steam_id64)
    if not path:
        return {}
    try:
        data = parse_vdf(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return {}
    fg = ci_get(data, "UserLocalConfigStore", "FamilyGroup")
    if not isinstance(fg, dict):
        return {}
    members = ci_get(fg, "members") or {}
    ids = []
    for m in members.values() if isinstance(members, dict) else []:
        acc = ci_get(m, "accountid") if isinstance(m, dict) else None
        if acc and str(acc).isdigit():
            ids.append(from_account_id(int(acc)))
    return {"name": ci_get(fg, "name") or "Steam Family", "member_steam_ids": list(dict.fromkeys(ids))}
