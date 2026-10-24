"""Settings.

  config.toml  (per-OS config dir)  – profiles: steam id, store country, budget, family…
  OS keyring                        – API keys / tokens (fallback: secrets.toml, mode 600)
  environment variables             – override everything (CI, GitHub Actions, one-off runs)

Precedence at runtime: CLI flags > env vars > config.toml > defaults.
"""
from __future__ import annotations

import ctypes
import hashlib
import locale
import os
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import platformdirs
import tomli_w

PROJECT_DIR = Path(__file__).resolve().parent.parent
_HOME = os.environ.get("SIFT_HOME", "").strip()   # portable / test installs: everything under one folder
CONFIG_DIR = Path(_HOME) if _HOME else Path(platformdirs.user_config_dir("sift", appauthor=False, roaming=True))
STATE_DIR = Path(_HOME) if _HOME else Path(platformdirs.user_state_dir("sift", appauthor=False))
for _d in (CONFIG_DIR, STATE_DIR):
    _d.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config.toml"
SECRETS_FILE = CONFIG_DIR / "secrets.toml"

# A portable/test install (SIFT_HOME) gets its own keyring namespace so it never sees the main install's keys.
KEYRING_SERVICE = "steamsift" if not _HOME else "steamsift@" + hashlib.sha1(_HOME.encode()).hexdigest()[:10]
# secret name -> environment variable that overrides it
SECRETS = {
    "steam_api_key": "STEAM_API_KEY",
    "itad_api_key": "ITAD_API_KEY",
    "telegram_token": "SIFT_TELEGRAM_TOKEN",
    "discord_webhook": "SIFT_DISCORD_WEBHOOK",
    "ntfy_token": "SIFT_NTFY_TOKEN",
    "smtp_password": "SIFT_SMTP_PASSWORD",
}

UI_LANGS = ("ru", "en")


def system_lang() -> str:
    """'ru' for Russian-family UIs (ru/uk/be/kk), otherwise 'en'."""
    code = ""
    if sys.platform == "win32":
        try:
            lid = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            code = {0x19: "ru", 0x22: "uk", 0x23: "be", 0x3F: "kk"}.get(lid, "en")
        except (AttributeError, OSError):
            pass
    if not code:
        raw = os.environ.get("LC_ALL") or os.environ.get("LANG") or (locale.getlocale()[0] or "")
        code = raw[:2].lower()
    return "ru" if code in ("ru", "uk", "be", "kk") else "en"


# --------------------------------------------------------------------------- model

def _build(cls, d: dict | None):
    """Dataclass from a dict, ignoring unknown keys (forward/backward compatible config files)."""
    d = d or {}
    return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Filters:
    game_lang: str = ""           # "" any | "subs" | "audio" — in game_lang_name (default: the UI language)
    game_lang_name: str = ""      # Steam language name ("russian", "turkish", …); "" = UI language
    deck: str = "any"             # any | playable | verified
    platforms: list[str] = field(default_factory=list)   # [] = any; else must support one of windows/mac/linux
    adult: bool = False           # show adult-only sexual content
    early_access: str = "show"    # show | hide
    vr_only: bool = False         # include VR-only games
    third_party: bool = True      # allow games that need an EA / Ubisoft / Rockstar … account
    family: bool = False          # also list games your Steam Family already shares (marked in blue)
    exclude_tags: list[str] = field(default_factory=list)  # English Steam tag names
    min_reviews: int = 50
    min_positive: int = 0
    explore: float = 0.15         # 0 = only familiar … 1 = adventurous
    elsewhere: str = "auto"       # auto | on | off — show cheaper official stores (ITAD)


DEFAULT_EVENTS = ["wish_lowest", "wish_target", "pick_strong", "ending", "dlc_lowest", "sale_start"]


@dataclass
class Notify:
    channels: list[str] = field(default_factory=list)    # telegram | discord | ntfy | desktop | email
    mode: str = "digest"          # digest | instant
    digest_time: str = "19:00"
    quiet: str = ""               # "23:00-09:00" — instant alerts wait until it ends
    events: list[str] = field(default_factory=lambda: list(DEFAULT_EVENTS))
    min_score: int = 80
    max_cards: int = 6            # per message burst; the rest go into the digest list
    paused_until: int = 0
    every: int = 60               # minutes between scheduled scans
    telegram_chat: str = ""
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str = ""
    email_to: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""


@dataclass
class Profile:
    steam_id: str = ""
    country: str = ""                 # store country, ISO-3166 alpha-2 (decides prices & availability)
    budget: float | None = None       # max price in the store's local currency
    min_discount: int = 20
    family: list[str] = field(default_factory=list)   # manual SteamID64s; empty = read from the Steam client
    seeds: list[int] = field(default_factory=list)    # favourite games picked during setup (cold start)
    filters: Filters = field(default_factory=Filters)
    notify: Notify = field(default_factory=Notify)

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d and k not in ("filters", "notify")}
        if known.get("budget") in ("", 0):
            known["budget"] = None
        return cls(**known, filters=_build(Filters, d.get("filters")), notify=_build(Notify, d.get("notify")))

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["budget"] is None:
            d.pop("budget")
        return d


@dataclass
class Settings:
    lang: str = ""                    # UI language; "" = follow the system
    active: str = "main"
    profiles: dict[str, Profile] = field(default_factory=lambda: {"main": Profile()})
    covers: str = "auto"             # cover art in the app: auto (best the terminal supports) | sixel | blocks | off
    macros: dict[str, str] = field(default_factory=dict)   # name -> sift flags ("-b 2 -g indie --lowest")
    remote_fetch_host: str = ""       # advanced: SSH host used when the store blocks this IP
    remote_fetch_script: str = ""

    @classmethod
    def load(cls) -> "Settings":
        if not CONFIG_FILE.exists():
            s = cls()
            if migrate_legacy(s):
                s.save()
            return s
        try:
            raw = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return cls()
        profiles = {n: Profile.from_dict(p) for n, p in (raw.get("profiles") or {}).items()} or {"main": Profile()}
        active = raw.get("active", "main")
        return cls(
            lang=raw.get("lang", ""),
            covers=raw.get("covers", "auto"),
            active=active if active in profiles else next(iter(profiles)),
            profiles=profiles,
            macros={str(k).lower(): str(v) for k, v in (raw.get("macros") or {}).items()},
            remote_fetch_host=raw.get("advanced", {}).get("remote_fetch_host", ""),
            remote_fetch_script=raw.get("advanced", {}).get("remote_fetch_script", ""),
        )

    def save(self) -> None:
        doc = {"lang": self.lang, "covers": self.covers, "active": self.active,
               "profiles": {n: p.to_dict() for n, p in self.profiles.items()}}
        if self.macros:
            doc["macros"] = dict(sorted(self.macros.items()))
        if self.remote_fetch_host:
            doc["advanced"] = {"remote_fetch_host": self.remote_fetch_host,
                               "remote_fetch_script": self.remote_fetch_script}
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text("# sift settings — edit freely or use `sift config set …`\n" + tomli_w.dumps(doc),
                       encoding="utf-8")
        os.replace(tmp, CONFIG_FILE)


# --------------------------------------------------------------------------- secrets

def _keyring():
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:  # noqa: BLE001 - any backend problem means "use the file fallback"
        return None


def _file_secrets() -> dict:
    try:
        return tomllib.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def get_secret(name: str) -> str:
    env = os.environ.get(SECRETS.get(name, ""), "").strip()
    if env:
        return env
    kr = _keyring()
    if kr:
        try:
            val = kr.get_password(KEYRING_SERVICE, name)
            if val:
                return val
        except Exception:  # noqa: BLE001
            pass
    return str(_file_secrets().get(name, ""))


def secret_source(name: str) -> str:
    if os.environ.get(SECRETS.get(name, ""), "").strip():
        return "env"
    kr = _keyring()
    if kr:
        try:
            if kr.get_password(KEYRING_SERVICE, name):
                return "keyring"
        except Exception:  # noqa: BLE001
            pass
    return "file" if _file_secrets().get(name) else ""


def set_secret(name: str, value: str) -> str:
    """Store a secret; returns where it went ('keyring' or 'file')."""
    value = value.strip()
    kr = _keyring()
    if kr:
        try:
            if value:
                kr.set_password(KEYRING_SERVICE, name, value)
            else:
                try:
                    kr.delete_password(KEYRING_SERVICE, name)
                except Exception:  # noqa: BLE001
                    pass
            return "keyring"
        except Exception:  # noqa: BLE001
            pass
    data = _file_secrets()
    if value:
        data[name] = value
    else:
        data.pop(name, None)
    SECRETS_FILE.write_text(tomli_w.dumps(data), encoding="utf-8")
    try:
        os.chmod(SECRETS_FILE, 0o600)
    except OSError:
        pass
    return "file"


# --------------------------------------------------------------------------- legacy .env migration

def _legacy_env_files() -> list[Path]:
    cands = [PROJECT_DIR / ".env", Path.cwd() / ".env", Path.home() / ".config" / "steamdeals" / ".env"]
    seen, out = set(), []
    for p in cands:
        rp = p.resolve()
        if p.is_file() and rp not in seen:
            seen.add(rp)
            out.append(p)
    return out


def migrate_legacy(s: Settings) -> bool:
    """Import a v1/v2 `.env` (STEAM_ID64, keys, region, balance) into config + keyring, once."""
    files = _legacy_env_files()
    if not files:
        return False
    from dotenv import dotenv_values

    vals: dict[str, str] = {}
    for f in files:
        vals.update({k: (v or "").strip() for k, v in dotenv_values(f).items()})
    if not vals.get("STEAM_ID64"):
        return False
    p = s.profiles.setdefault("main", Profile())
    p.steam_id = vals["STEAM_ID64"]
    p.country = vals.get("STEAM_COUNTRY", "").upper()
    try:
        p.budget = float(vals["STEAM_BALANCE"]) if vals.get("STEAM_BALANCE") else None
    except ValueError:
        p.budget = None
    for name, env in SECRETS.items():
        if vals.get(env):
            set_secret(name, vals[env])
    s.remote_fetch_host = vals.get("REMOTE_FETCH_HOST", "")
    s.remote_fetch_script = vals.get("REMOTE_FETCH_SCRIPT", "")
    for f in files:
        try:
            f.rename(f.with_name(".env.migrated"))
        except OSError:
            pass
    return True


# --------------------------------------------------------------------------- runtime

@dataclass
class Runtime:
    """The effective values for this run (profile + env overrides + CLI flags).

    API keys are read from the keychain lazily — the first time something actually needs them."""
    settings: Settings
    profile_name: str
    profile: Profile
    lang: str
    steam_id: str
    country: str
    budget: float | None
    min_discount: int
    family: list[str]
    _keys: dict = field(default_factory=dict)

    def _key(self, name: str) -> str:
        if name not in self._keys:
            self._keys[name] = get_secret(name)
        return self._keys[name]

    @property
    def steam_api_key(self) -> str:
        return self._key("steam_api_key")

    @steam_api_key.setter
    def steam_api_key(self, value: str) -> None:
        self._keys["steam_api_key"] = value

    @property
    def itad_api_key(self) -> str:
        return self._key("itad_api_key")

    @itad_api_key.setter
    def itad_api_key(self, value: str) -> None:
        self._keys["itad_api_key"] = value

    @property
    def steam_lang(self) -> str:
        return {"ru": "russian", "en": "english"}.get(self.lang, "english")


cfg: Runtime  # set by activate()


def activate(profile_name: str | None = None) -> Runtime:
    global cfg
    s = Settings.load()
    name = profile_name or os.environ.get("SIFT_PROFILE") or s.active
    if name not in s.profiles:
        s.profiles[name] = Profile()
    p = s.profiles[name]
    env = os.environ.get
    lang = (env("SIFT_LANG") or s.lang or "en").lower()      # English unless chosen (setup, sift config set lang ru)
    budget = p.budget
    if env("STEAM_BALANCE"):
        try:
            budget = float(env("STEAM_BALANCE"))
        except ValueError:
            pass
    fam_env = env("SIFT_FAMILY")
    n = p.notify
    if env("SIFT_TELEGRAM_CHAT"):
        n.telegram_chat = env("SIFT_TELEGRAM_CHAT")
    if env("SIFT_NTFY_TOPIC"):
        n.ntfy_topic = env("SIFT_NTFY_TOPIC")
    if env("SIFT_NOTIFY_MODE") in ("digest", "instant"):
        n.mode = env("SIFT_NOTIFY_MODE")
    if env("SIFT_CHANNELS"):
        n.channels = [c.strip() for c in env("SIFT_CHANNELS").split(",") if c.strip()]
    elif not n.channels:
        n.channels = [c for c, ok in (("telegram", env("SIFT_TELEGRAM_TOKEN") and n.telegram_chat),
                                      ("discord", env("SIFT_DISCORD_WEBHOOK")), ("ntfy", n.ntfy_topic)) if ok]
    cfg = Runtime(
        settings=s,
        profile_name=name,
        profile=p,
        lang=lang if lang in UI_LANGS else "en",
        steam_id=(env("STEAM_ID64") or p.steam_id).strip(),
        country=(env("STEAM_COUNTRY") or p.country).strip().upper(),
        budget=budget,
        min_discount=p.min_discount,
        family=[x.strip() for x in fam_env.split(",")] if fam_env else list(p.family),
    )
    return cfg
