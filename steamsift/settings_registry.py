"""Every user-changeable setting in one table: `sift config set <key> <value>`, the wizard and the TUI use it.

Each entry knows where the value lives (profile / filters / notify / settings / secret), how to parse
user input and how to show it back.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from . import config, region, steamid
from .i18n import t


class SettingError(ValueError):
    pass


def _bool(v: str) -> bool:
    v = v.strip().lower()
    if v in ("on", "yes", "true", "1", "да", "вкл"):
        return True
    if v in ("off", "no", "false", "0", "нет", "выкл"):
        return False
    raise SettingError(t("set_bool"))


def _choice(*opts: str) -> Callable[[str], str]:
    def parse(v: str) -> str:
        v = v.strip().lower()
        if v not in opts:
            raise SettingError(t("set_choice", opts=" | ".join(opts)))
        return v
    return parse


def _int(lo: int, hi: int) -> Callable[[str], int]:
    def parse(v: str) -> int:
        try:
            n = int(v.strip().rstrip("%"))
        except ValueError:
            raise SettingError(t("set_number", lo=lo, hi=hi)) from None
        if not lo <= n <= hi:
            raise SettingError(t("set_number", lo=lo, hi=hi))
        return n
    return parse


def _float01(v: str) -> float:
    try:
        x = float(v.replace(",", "."))
    except ValueError:
        raise SettingError(t("set_number", lo=0, hi=1)) from None
    if not 0 <= x <= 1:
        raise SettingError(t("set_number", lo=0, hi=1))
    return x


def _time(v: str) -> str:
    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", v.strip()):
        raise SettingError(t("set_time"))
    h, m = v.strip().split(":")
    return f"{int(h):02d}:{m}"


def _quiet(v: str) -> str:
    v = v.strip()
    if v.lower() in ("off", "", "-"):
        return ""
    parts = v.split("-")
    if len(parts) != 2:
        raise SettingError(t("set_quiet"))
    return f"{_time(parts[0])}-{_time(parts[1])}"


def _list(v: str) -> list[str]:
    if v.strip().lower() in ("off", "none", "-", ""):
        return []
    return [x.strip() for x in re.split(r"[,;]", v) if x.strip()]


def _platforms(v: str) -> list[str]:
    vals = [x.lower() for x in _list(v) if x.lower() != "any"]
    bad = [x for x in vals if x not in ("windows", "mac", "linux")]
    if bad:
        raise SettingError(t("set_choice", opts="any | windows, mac, linux"))
    return vals


def _budget(v: str) -> float | None:
    if v.strip().lower() in ("off", "none", "0", "-", ""):
        return None
    try:
        return float(v.replace(",", ".").replace(" ", "").replace("\u202f", ""))
    except ValueError:
        raise SettingError(t("set_number", lo=0, hi="∞")) from None


def _country(v: str) -> str:
    c = config.cfg
    matches = region.search(v, c.lang)
    if not matches:
        raise SettingError(t("cfg_country_unknown", q=v))
    exact = [m for m in matches if m == v.strip().upper() or v.strip().lower() in
             (region.name(m, "en").lower(), region.name(m, "ru").lower())]
    if len(matches) > 1 and not exact:
        raise SettingError(t("cfg_country_ambiguous", q=v,
                             opts=", ".join(f"{region.name(m, c.lang)} ({m})" for m in matches[:8])))
    code = (exact or matches)[0]
    if not region.has_store(code):
        raise SettingError(t("err_no_store", country=region.name(code, c.lang)))
    return code


def _steam(v: str) -> str:
    sid = steamid.resolve(v, config.cfg.steam_api_key)
    if not sid:
        parsed = steamid.parse(v)
        raise SettingError(t("err_need_key_vanity") if parsed and parsed[0] == "vanity" and not
                           config.cfg.steam_api_key else t("err_bad_profile", q=v))
    return sid


def _family(v: str) -> list[str]:
    if v.strip().lower() in ("auto", "off", ""):
        return []
    out = []
    for part in re.split(r"[\s,;]+", v.strip()):
        if part:
            out.append(_steam(part))
    return list(dict.fromkeys(out))


def _lang(v: str) -> str:
    v = v.strip().lower()
    if v in ("auto", ""):
        return ""
    if v not in config.UI_LANGS:
        raise SettingError(t("set_choice", opts="ru | en | auto"))
    return v


def _game_lang(v: str) -> tuple[str, str]:
    """'audio', 'subs russian', 'any'."""
    from .engine import ELANG
    parts = v.strip().lower().split()
    mode = parts[0] if parts else "any"
    if mode not in ("any", "subs", "audio"):
        raise SettingError(t("set_choice", opts="any | subs [language] | audio [language]"))
    lang = parts[1] if len(parts) > 1 else ""
    if lang and lang not in ELANG:
        raise SettingError(t("set_choice", opts=", ".join(ELANG)))
    return ("" if mode == "any" else mode), lang


def _events(v: str) -> list[str]:
    vals = _list(v)
    bad = [x for x in vals if x not in config.DEFAULT_EVENTS]
    if bad:
        raise SettingError(t("set_choice", opts=", ".join(config.DEFAULT_EVENTS)))
    return vals


def _channels(v: str) -> list[str]:
    from .notify.runner import CHANNELS
    vals = [x.lower() for x in _list(v)]
    bad = [x for x in vals if x not in CHANNELS]
    if bad:
        raise SettingError(t("set_choice", opts=", ".join(CHANNELS)))
    return vals


@dataclass
class Setting:
    key: str
    where: str                       # profile | filters | notify | settings | secret
    attr: str
    parse: Callable[[str], Any]
    help_key: str


REGISTRY: list[Setting] = [
    Setting("steam", "profile", "steam_id", _steam, "h_steam"),
    Setting("country", "profile", "country", _country, "h_country"),
    Setting("lang", "settings", "lang", _lang, "h_lang"),
    Setting("covers", "settings", "covers", _choice("auto", "sixel", "blocks", "off"), "h_covers"),
    Setting("budget", "profile", "budget", _budget, "h_budget"),
    Setting("min-discount", "profile", "min_discount", _int(0, 99), "h_min_discount"),
    Setting("family", "profile", "family", _family, "h_family"),
    Setting("steam-key", "secret", "steam_api_key", str, "h_steam_key"),
    Setting("itad-key", "secret", "itad_api_key", str, "h_itad_key"),
    # filters
    Setting("game-lang", "filters", "game_lang", _game_lang, "h_game_lang"),
    Setting("deck", "filters", "deck", _choice("any", "playable", "verified"), "h_deck"),
    Setting("platforms", "filters", "platforms", _platforms, "h_platforms"),
    Setting("adult", "filters", "adult", _bool, "h_adult"),
    Setting("early-access", "filters", "early_access", _choice("show", "hide"), "h_early_access"),
    Setting("vr", "filters", "vr_only", _bool, "h_vr"),
    Setting("third-party", "filters", "third_party", _bool, "h_third_party"),
    Setting("family", "filters", "family", _bool, "h_family"),
    Setting("exclude-tags", "filters", "exclude_tags", _list, "h_exclude_tags"),
    Setting("min-reviews", "filters", "min_reviews", _int(0, 1_000_000), "h_min_reviews"),
    Setting("min-positive", "filters", "min_positive", _int(0, 100), "h_min_positive"),
    Setting("explore", "filters", "explore", _float01, "h_explore"),
    Setting("elsewhere", "filters", "elsewhere", _choice("auto", "on", "off"), "h_elsewhere"),
    # notifications
    Setting("channels", "notify", "channels", _channels, "h_channels"),
    Setting("notify-mode", "notify", "mode", _choice("digest", "instant"), "h_notify_mode"),
    Setting("digest-time", "notify", "digest_time", _time, "h_digest_time"),
    Setting("quiet", "notify", "quiet", _quiet, "h_quiet"),
    Setting("events", "notify", "events", _events, "h_events"),
    Setting("min-score", "notify", "min_score", _int(0, 100), "h_min_score"),
    Setting("every", "notify", "every", _int(15, 1440), "h_every"),
    Setting("ntfy-topic", "notify", "ntfy_topic", str, "h_ntfy_topic"),
    Setting("ntfy-server", "notify", "ntfy_server", str, "h_ntfy_server"),
    Setting("email-to", "notify", "email_to", str, "h_email_to"),
    Setting("smtp-host", "notify", "smtp_host", str, "h_smtp_host"),
    Setting("smtp-port", "notify", "smtp_port", _int(1, 65535), "h_smtp_port"),
    Setting("smtp-user", "notify", "smtp_user", str, "h_smtp_user"),
    Setting("smtp-password", "secret", "smtp_password", str, "h_smtp_password"),
    Setting("discord-webhook", "secret", "discord_webhook", str, "h_discord_webhook"),
    Setting("telegram-token", "secret", "telegram_token", str, "h_telegram_token"),
    Setting("telegram-chat", "notify", "telegram_chat", str, "h_telegram_chat"),
]
BY_KEY = {s.key: s for s in REGISTRY}
SECRET_KEYS = {s.key for s in REGISTRY if s.where == "secret"}


def _target(s: Setting):
    c = config.cfg
    return {"profile": c.profile, "filters": c.profile.filters, "notify": c.profile.notify,
            "settings": c.settings}[s.where]


def get(key: str) -> Any:
    s = BY_KEY[key]
    if s.where == "secret":
        return config.secret_source(s.attr)
    if key == "game-lang":
        f = config.cfg.profile.filters
        return f"{f.game_lang or 'any'} {f.game_lang_name}".strip()
    return getattr(_target(s), s.attr)


def apply(key: str, raw: str) -> Any:
    """Parse, validate and store; raises SettingError with a friendly message. Caller saves settings."""
    s = BY_KEY.get(key)
    if not s:
        raise SettingError(t("cfg_unknown_key", k=key, keys=", ".join(BY_KEY)))
    value = s.parse(raw)
    if s.where == "secret":
        return config.set_secret(s.attr, value)
    if key == "game-lang":
        mode, lang = value
        f = config.cfg.profile.filters
        f.game_lang, f.game_lang_name = mode, lang
        return value
    setattr(_target(s), s.attr, value)
    c = config.cfg                       # keep the live runtime in sync with the profile
    if key == "steam":
        c.steam_id = value
    elif key == "country":
        c.country = value
    elif key == "budget":
        c.budget = value
    elif key == "min-discount":
        c.min_discount = value
    elif key == "family":
        c.family = value
    elif key == "lang":
        c.lang = value or "en"
    return value


def show(key: str) -> str:
    v = get(key)
    if key in SECRET_KEYS:
        return f"✓ {v}" if v else "—"
    if isinstance(v, bool):
        return "on" if v else "off"
    if isinstance(v, list):
        return ", ".join(map(str, v)) or "—"
    if key == "budget":
        return region.price_format(config.cfg.country or "US").amount(v) if v else "—"
    if key == "country":
        return f"{region.label(v, config.cfg.lang)} ({v})" if v else "—"
    return str(v) if v not in ("", None) else "—"
