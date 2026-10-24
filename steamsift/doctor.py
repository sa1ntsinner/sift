"""`sift doctor`: check every moving part and say exactly how to fix what's wrong."""
from __future__ import annotations

import platform
import sys
from dataclasses import dataclass

from . import __version__, config, region, schedule
from .config import CONFIG_FILE, get_secret
from .db import DB_FILE, db
from .i18n import t
from .net import SESSION, request_json

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"


@dataclass
class Check:
    status: str
    title: str
    detail: str = ""
    fix: str = ""


def check_steam_key(key: str) -> bool | None:
    """True valid, False rejected, None network problem."""
    try:
        r = SESSION.get("https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/",
                        params={"key": key, "steamids": "76561197960287930"}, timeout=10)
    except Exception:  # noqa: BLE001
        return None
    return r.status_code == 200 if r.status_code in (200, 401, 403) else None


def check_itad_key(key: str) -> bool | None:
    try:
        r = SESSION.get("https://api.isthereanydeal.com/games/lookup/v1", params={"key": key, "appid": 620},
                        timeout=10)
    except Exception:  # noqa: BLE001
        return None
    return r.status_code == 200 if r.status_code in (200, 401, 403) else None


def wishlist_count(steam_id: str) -> int | None:
    data = request_json("https://api.steampowered.com/IWishlistService/GetWishlistItemCount/v1/",
                        params={"steamid": steam_id})
    return (data or {}).get("response", {}).get("count") if isinstance(data, dict) else None


def run_checks() -> list[Check]:
    from .steam import get_owned_games, get_player_summaries, search_specials
    from .localsteam import family_from_client

    c = config.cfg
    out: list[Check] = []
    add = out.append
    add(Check(OK, f"sift {__version__}", f"Python {platform.python_version()} · {platform.system()} {platform.release()}"))
    add(Check(OK if CONFIG_FILE.exists() else WARN, t("dr_config"), str(CONFIG_FILE),
              "" if CONFIG_FILE.exists() else "sift setup"))

    key_ok = check_steam_key(c.steam_api_key) if c.steam_api_key else False
    if key_ok:
        add(Check(OK, t("dr_steam_key"), t("dr_valid")))
    elif key_ok is None:
        add(Check(WARN, t("dr_steam_key"), t("dr_network")))
    else:
        add(Check(FAIL, t("dr_steam_key"), t("cfg_not_set") if not c.steam_api_key else t("dr_rejected"),
                  "sift config set steam-key   (https://steamcommunity.com/dev/apikey)"))

    if not c.steam_id:
        add(Check(FAIL, t("dr_profile"), t("cfg_not_set"), "sift config set steam <link>"))
    elif key_ok:
        summ = get_player_summaries([c.steam_id]).get(c.steam_id)
        if not summ:
            add(Check(FAIL, t("dr_profile"), c.steam_id, "sift config set steam <link>"))
        elif summ.get("visibility") != 3:
            add(Check(FAIL, t("dr_profile"), t("dr_private_profile", name=summ["name"]),
                      "https://steamcommunity.com/my/edit/settings"))
        else:
            add(Check(OK, t("dr_profile"), f"{summ['name']} · {c.steam_id}"))
            games = get_owned_games(c.steam_id)
            if not games:
                add(Check(FAIL, t("dr_game_details"), t("dr_games_hidden"), "https://steamcommunity.com/my/edit/settings"))
            elif not any(g.get("playtime_forever") for g in games.values()):
                add(Check(WARN, t("dr_game_details"), t("dr_playtime_hidden", n=len(games)),
                          "https://steamcommunity.com/my/edit/settings"))
            else:
                add(Check(OK, t("dr_game_details"), t("dr_games_n", n=len(games))))
    wl = wishlist_count(c.steam_id) if c.steam_id else None
    if wl is not None:
        add(Check(OK if wl else WARN, t("dr_wishlist"), str(wl) if wl else t("dr_wishlist_empty")))

    if not c.country:
        add(Check(FAIL, t("dr_region"), t("cfg_not_set"), "sift config set country <code>"))
    elif not region.has_store(c.country):
        add(Check(FAIL, t("dr_region"), t("err_no_store", country=region.name(c.country, c.lang)),
                  "sift config set country <code>"))
    else:
        ip = region.detect_ip_country()
        label = f"{region.label(c.country, c.lang)} ({c.country})"
        if ip and ip != c.country:
            add(Check(INFO, t("dr_region"), label + " · " + t("ip_mismatch", ip=region.name(ip, c.lang),
                                                               country=region.name(c.country, c.lang))))
        else:
            add(Check(OK, t("dr_region"), label))
        if c.country and region.has_store(c.country):
            try:
                n = len(search_specials(0, 25))
                add(Check(OK if n else WARN, t("dr_store"), t("dr_store_ok", n=n) if n else t("dr_network")))
            except Exception:  # noqa: BLE001
                add(Check(WARN, t("dr_store"), t("dr_network")))

    if c.family:
        add(Check(OK, t("family"), f"{len(c.family)} · {t('family_src_manual')}"))
    elif c.steam_id:
        fam = family_from_client(c.steam_id)
        if fam:
            add(Check(OK, t("dr_family"), f"{fam['name']} · {len(fam['member_steam_ids'])} · {t('family_src_client')}"))
        else:
            add(Check(INFO, t("dr_family"), t("dr_no_family"), "sift config set family <links…>"))

    if c.itad_api_key:
        ok = check_itad_key(c.itad_api_key)
        add(Check(OK if ok else (WARN if ok is None else FAIL), "IsThereAnyDeal",
                  t("dr_valid") if ok else (t("dr_network") if ok is None else t("dr_rejected")),
                  "" if ok else "sift config set itad-key"))
    else:
        add(Check(INFO, "IsThereAnyDeal", t("dr_itad_optional"), "sift config set itad-key"))

    n = c.profile.notify
    if not n.channels:
        add(Check(INFO, t("dr_notify"), t("dr_notify_off"), "sift notify setup telegram"))
    for ch in n.channels:
        if ch == "telegram":
            from .notify.telegram import Telegram, TelegramError
            token = get_secret("telegram_token")
            try:
                me = Telegram(token).get_me() if token else None
                add(Check(OK if me and n.telegram_chat else FAIL, "Telegram",
                          f"@{me['username']} → chat {n.telegram_chat}" if me and n.telegram_chat
                          else t("dr_tg_incomplete"), "" if me and n.telegram_chat else "sift notify setup telegram"))
            except TelegramError as e:
                add(Check(FAIL, "Telegram", str(e), "sift notify setup telegram"))
        elif ch == "discord":
            hook = get_secret("discord_webhook")
            ok = bool(hook) and SESSION.get(hook, timeout=10).status_code == 200
            add(Check(OK if ok else FAIL, "Discord", t("dr_valid") if ok else t("dr_rejected"),
                      "" if ok else "sift notify setup discord"))
        elif ch == "ntfy":
            add(Check(OK if n.ntfy_topic else FAIL, "ntfy", f"{n.ntfy_server}/{n.ntfy_topic}",
                      "" if n.ntfy_topic else "sift notify setup ntfy"))
        else:
            add(Check(OK, ch, t("dr_enabled")))
    if n.channels:
        installed, detail = schedule.status(c.profile_name)
        add(Check(OK if installed else INFO, t("dr_schedule"), detail or (t("dr_enabled") if installed else
                                                                           t("dr_schedule_off")),
                  "" if installed else "sift notify enable"))

    try:
        db().execute("SELECT 1")
        size = DB_FILE.stat().st_size / 1e6 if DB_FILE.exists() else 0
        add(Check(OK, t("dr_db"), f"{DB_FILE} · {size:.1f} MB"))
    except Exception as e:  # noqa: BLE001
        add(Check(FAIL, t("dr_db"), str(e)))
    if sys.version_info < (3, 11):
        add(Check(FAIL, "Python", platform.python_version(), "Python 3.11+"))
    return out


def summary(checks: list[Check]) -> tuple[int, int, int]:
    ok = sum(1 for x in checks if x.status in (OK, INFO))
    return ok, sum(1 for x in checks if x.status == WARN), sum(1 for x in checks if x.status == FAIL)
