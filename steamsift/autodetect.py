"""What setup can find on this computer, only when the user agrees: Steam accounts, Steam Family, keys.

Nothing is sent anywhere. We read Steam's own text files (config/loginusers.vdf, userdata/*/localconfig.vdf)
and, while a key step is open, the clipboard, so a key copied from the browser fills itself in.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

from .localsteam import ci_get, family_from_client, parse_vdf, steam_roots

STEAM_KEY = re.compile(r"\b[0-9A-F]{32}\b")
ITAD_KEY = re.compile(r"\b[0-9a-f]{40}\b")


@dataclass
class Account:
    steam_id: str
    persona: str
    recent: bool = False
    stamp: int = 0


@dataclass
class Found:
    steam_root: str = ""
    accounts: list[Account] = field(default_factory=list)
    family: dict = field(default_factory=dict)

    @property
    def account(self) -> Account | None:
        return self.accounts[0] if self.accounts else None


def accounts() -> list[Account]:
    """Accounts that signed in to Steam on this PC, the one used last first."""
    out: dict[str, Account] = {}
    for root in steam_roots():
        path = root / "config" / "loginusers.vdf"
        try:
            users = ci_get(parse_vdf(path.read_text(encoding="utf-8", errors="ignore")), "users") or {}
        except OSError:
            continue
        for sid, u in users.items() if isinstance(users, dict) else []:
            if not (isinstance(u, dict) and str(sid).isdigit() and len(str(sid)) == 17):
                continue
            stamp = ci_get(u, "Timestamp") or "0"
            out.setdefault(sid, Account(sid, ci_get(u, "PersonaName") or "", ci_get(u, "MostRecent") == "1",
                                        int(stamp) if str(stamp).isdigit() else 0))
    return sorted(out.values(), key=lambda a: (not a.recent, -a.stamp))


def scan() -> Found:
    roots = steam_roots()
    found = Found(steam_root=str(roots[0]) if roots else "", accounts=accounts())
    if found.account:
        found.family = family_from_client(found.account.steam_id)
    return found


def clipboard_text() -> str:
    """The clipboard as text, or '' when it can't be read (no display, no tool, not text)."""
    try:
        if sys.platform == "win32":
            return _windows_clipboard()
        for cmd in (["pbpaste"], ["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"],
                    ["xsel", "--clipboard", "--output"]):
            if shutil.which(cmd[0]):
                return subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return ""


def _windows_clipboard() -> str:
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    CF_UNICODETEXT = 13
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(ptr) if ptr else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def key_in(text: str, kind: str) -> str:
    """The first Steam (32 hex, upper case) or ITAD (40 hex, lower case) key in `text`."""
    m = (STEAM_KEY if kind == "steam" else ITAD_KEY).search(text or "")
    return m.group(0) if m else ""
