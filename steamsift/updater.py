"""`sift update`: find out how sift was installed and update it the same way.

    binary   the file from install.sh / install.ps1 or a GitHub release → download the new one and swap it in
    uv       `uv tool install steamsift`  → uv tool upgrade steamsift
    pipx     `pipx install steamsift`     → pipx upgrade steamsift
    pip      `pip install steamsift`      → python -m pip install --upgrade steamsift
    source   a git checkout (pip install -e .) → git pull --ff-only
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .db import DAY, Cache

REPO = "sa1ntsinner/sift"
PACKAGE = "steamsift"
_latest_cache = Cache("latest_version", volatile=True)


def parse(v: str) -> tuple[int, ...]:
    """'v0.3.10' → (0, 3, 10); anything odd sorts as oldest."""
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split("."))
    except ValueError:
        return (0,)


def latest(cached: bool = True) -> str:
    """The newest released version ('' when GitHub can't be reached). Cached for a day."""
    if cached:
        hit = _latest_cache.get("v", DAY)
        if hit:
            return hit
    from .net import request_json
    data = request_json(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=8, retries=1)
    tag = (data or {}).get("tag_name", "") if isinstance(data, dict) else ""
    version = tag.lstrip("v")
    if version:
        _latest_cache.set("v", version)
    return version


def newer(cached: bool = True) -> str:
    """The latest version if it is newer than this one, else ''."""
    v = latest(cached)
    return v if v and parse(v) > parse(__version__) else ""


def method() -> str:
    """binary | uv | pipx | source | pip."""
    if getattr(sys, "frozen", False):
        return "binary"
    root = Path(__file__).resolve().parent.parent
    if (root / ".git").exists() and (root / "pyproject.toml").exists():
        return "source"
    prefix = Path(sys.prefix).as_posix().lower()
    if "/uv/tools/" in prefix or "/uv/tool/" in prefix:
        return "uv"
    if "/pipx/venvs/" in prefix:
        return "pipx"
    return "pip"


def asset_name() -> str:
    machine = platform.machine().lower()
    if sys.platform == "win32":
        return "sift-windows-x64.exe"
    if sys.platform == "darwin" and machine in ("arm64", "aarch64"):
        return "sift-macos-arm64"
    if sys.platform.startswith("linux") and machine in ("x86_64", "amd64"):
        return "sift-linux-x64"
    return ""


def command(how: str) -> list[str]:
    """The command that updates a non-binary install."""
    if how == "uv":
        return ["uv", "tool", "upgrade", PACKAGE] if shutil.which("uv") else \
            [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE]
    if how == "pipx":
        return ["pipx", "upgrade", PACKAGE]
    if how == "source":
        return ["git", "-C", str(Path(__file__).resolve().parent.parent), "pull", "--ff-only"]
    return [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE]


def replace_binary(version: str, exe: Path | None = None, download=None, verify=None) -> Path:
    """Download the release file for this platform next to the running binary and swap it in.

    Windows can't overwrite a running .exe but can rename it, so the old one becomes sift.old.exe and is
    removed on the next start (cleanup()). Returns the path of the new binary."""
    exe = Path(exe or sys.executable)
    name = asset_name()
    if not name:
        raise RuntimeError("no release file for this platform")
    url = f"https://github.com/{REPO}/releases/download/v{version}/{name}"
    part = exe.with_name(exe.name + ".part")
    (download or _download)(url, part)
    if os.name != "nt":
        part.chmod(0o755)
    problem = (verify or _starts)(part, version)
    if problem:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"the downloaded file did not start: {problem}")
    if os.name == "nt":
        old = exe.with_name(exe.stem + ".old" + exe.suffix)
        old.unlink(missing_ok=True)
        exe.replace(old)
    part.replace(exe)
    return exe


def _starts(path: Path, version: str) -> str:
    """'' when `path --version` prints the expected version, else what went wrong."""
    check = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=60)
    return "" if check.returncode == 0 and version in check.stdout else (check.stdout or check.stderr).strip() or "?"


def _download(url: str, dest: Path) -> None:
    from .net import SESSION
    with SESSION.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)


def cleanup() -> None:
    """Remove the previous binary a Windows update left behind."""
    if getattr(sys, "frozen", False) and os.name == "nt":
        exe = Path(sys.executable)
        try:
            exe.with_name(exe.stem + ".old" + exe.suffix).unlink(missing_ok=True)
        except OSError:
            pass
