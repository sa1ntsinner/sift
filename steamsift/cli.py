"""sift — taste-aware Steam deals.

  sift                 the app: picks, discover, wishlist, DLC     sift --print   the same as a table (also when piped)
  sift -x              discover: great deals outside your genres   sift -w | -t   wishlist | picks
  sift -b 2 -g indie -L   ≤ 2, indie, record lows (any filters)    sift <macro>   saved filters: sift macro add …
  sift info <game>     price, history, match & verdict            sift setup     guided first-time setup
  sift open <#>        open a result in the browser               sift doctor    check everything
  sift hide <#>        ⊘ don't recommend (hidden · unhide)        sift calendar  Steam sales & fests
  sift target <#> <p>  tell me when it costs ≤ p (or "lowest")    sift notify    alerts: setup | test | run | enable
  sift dlc · dna · family                                         sift config    settings · sift profile — accounts

macros:  sift macro add cheap -b 2 -g indie --lowest   →   sift cheap   (combine: sift cheap gems -d 80)
"""
from __future__ import annotations

from dataclasses import asdict
from .recommender import Verdict

import argparse
import datetime as dt
import getpass
import os
import secrets
import shlex
import sys
import time
import webbrowser

from rich.text import Text

from . import __version__, config, engine, prefs, query, region, schedule, settings_registry as reg, ui
from .config import CONFIG_FILE, Profile, get_secret, set_secret
from .db import DB_FILE, Cache, clear_cache, set_refresh
from .i18n import day_month, t
from .steam import get_items, store_lookup

console = ui.console
_last = Cache("last")


def cfg() -> config.Runtime:
    return config.cfg


def _status(key: str):
    return console.status(f"[grey50]{t(key)}", spinner="dots")


def _save_last(items) -> None:
    _last.set(cfg().profile_name, [[i.appid, i.name] for i in items])


def _load_last() -> list:
    return _last.get(cfg().profile_name) or []


# --------------------------------------------------------------------------- setup gate

def ready(quiet: bool = False) -> bool:
    c = cfg()
    if not c.steam_id or not c.steam_api_key:
        if not quiet:
            ui.error(t("err_not_configured"))
            ui.plain("  " + t("hint_setup"), "bold")       # the wizard is the easy way, so say it first
            ui.plain(t("setup_steps"), "grey62")
            console.print()
        return False
    if not c.country:
        ip = region.detect_ip_country()
        ui.error(t("err_no_country", ip=ip, name=region.name(ip, c.lang)) if ip else t("err_no_country_noip"))
        return False
    if not region.has_store(c.country):
        ui.error(t("err_no_store", country=region.name(c.country, c.lang)))
        return False
    return True


def _privacy(ctx: engine.Context) -> None:
    if not ctx.lib.games_visible:
        ui.warn(t("err_private"))


# --------------------------------------------------------------------------- deals & friends

def _query(args) -> query.Query:
    return getattr(args, "query", None) or query.Query()


def describe(q: query.Query) -> str:
    """'discover · ≤ $2.00 · indie · ★ record low' for macro lists and headers."""
    parts = [t({"picks": "ui_tab_picks", "discover": "ui_tab_discover", "wish": "ui_tab_wish"}[q.tab]).lower()
             if q.tab in ("picks", "discover", "wish") else ("dlc" if q.tab == "dlc" else "")]
    parts += q.chips()
    if q.sort != "score":
        parts.append("↓ " + t(f"ui_sort_{q.sort}"))
    return " · ".join(p for p in parts if p) or t("m_all_defaults")


def _query_line(q: query.Query) -> None:
    chips = q.chips()
    if not chips and not q.macros:
        return
    line = Text("  ⚙ ", style=ui.ACCENT)
    if q.macros:
        line.append(" ".join(q.macros), style="bold magenta")
        line.append("  ")
    line.append(" · ".join(chips), style="")
    console.print(line)


def _rec_to_dict(r) -> dict:
    i = r.item
    h = getattr(r, "hist", None)
    return {
        "appid": i.appid,
        "name": i.name,
        "price": ui.price_text(i),
        "final_cents": i.final_cents,
        "orig_cents": i.orig_cents,
        "cut": i.cut,
        "score": round(getattr(r, "score", 0.0), 1),
        "deal_score": round(getattr(r, "deal_score", 0.0), 1),
        "taste_pct": getattr(r, "taste_pct", 0),
        "is_atl": bool(h and h.is_atl(i.cut)),
        "is_2y_low": bool(h and h.is_2y_low(i.cut)),
        "best_cut": h.best_cut if h else 0,
        "low_2y_cut": h.low_2y_cut if h else 0,
        "verdict": asdict(getattr(r, "verdict", Verdict())),
        "history": asdict(h) if h else None,
        **(asdict(h) if h else {}),
        "rarity": h.rarity(i.cut) if h else 0.0,
        "bundle": getattr(r, "extras", {}).get("bundle") or ({"badge": i.bundle_badge()} if i.bundle_badge() else None),
        "review_pct": i.review_pct,
        "review_count": i.review_count,
        "why": getattr(r, "why", ""),
        "url": i.url,
    }


def cmd_deals(args) -> None:
    q = _query(args)
    if q.tab == "dlc":
        return cmd_dlc(args)
    show = {q.tab} if q.tab else {"wish", "picks"}
    with _status("sp_library"):
        ctx = engine.Context(engine.search_many(engine.BASE_PAGES))
    with _status("sp_sift"):
        ctx.load_pool()
    if "discover" in show:
        with _status("sp_discover"):
            ctx.load_discovery_pool()
    need_hist = q.buy or q.lowest or q.low_2y or q.near or q.rare or q.sort in ("atl", "rarity", "deal")
    with _status("sp_history"):
        d = engine.build_digest(ctx, limit=max(args.limit, 12), min_discount=0, budget=0,
                                show_wish="wish" in show, show_picks="picks" in show, discover="discover" in show,
                                history_all=need_hist)
    wish, picks, finds = q.apply(d.wish), q.apply(d.picks), q.apply(d.discover)
    if getattr(args, "json", False):
        import json as _json
        payload = {}
        if "wish" in show:
            payload["wishlist"] = [_rec_to_dict(r) for r in wish[: args.limit]]
        if "picks" in show:
            payload["picks"] = [_rec_to_dict(r) for r in picks[: args.limit]]
        if "discover" in show:
            payload["discover"] = [_rec_to_dict(r) for r in finds[: args.limit]]
        sys.stdout.write(_json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return
    ui.header(ctx.lib, ctx.profile, len(ctx.hidden), engine.itad.available(), len(ctx.family_shared))
    _query_line(q)
    _privacy(ctx)
    shown = []
    hist = engine.itad.available()
    if "wish" in show:
        ui.section(t("sec_wishlist"), "♥", min(args.limit, len(wish)), len(wish))
        if wish:
            ui.rec_table(wish[: args.limit], start=1, show_history=hist)
            shown += [r.item for r in wish[: args.limit]]
        else:
            ui.empty(t("empty_wish"))
    if "picks" in show:
        ui.section(t("sec_picks"), "✦", min(args.limit, len(picks)), len(picks))
        if picks:
            ui.rec_table(picks[: args.limit], start=len(shown) + 1, show_history=hist)
            shown += [r.item for r in picks[: args.limit]]
        else:
            ui.empty(t("empty_picks"))
    if "discover" in show:
        ui.section(t("sec_discover"), "✧", min(args.limit, len(finds)), len(finds))
        if finds:
            ui.rec_table(finds[: args.limit], start=len(shown) + 1, show_history=hist)
            shown += [r.item for r in finds[: args.limit]]
        else:
            ui.empty(t("empty_discover"))
    _save_last(shown)
    for line in ui.calendar_lines(d):
        console.print(line)
    ui.footer(t("scanned", n=d.scanned) if show != {"wish"} else "",
              t("wish_unavailable", n=d.unavailable, country=engine.country_name()) if d.unavailable and "wish" in show
              else "")


def cmd_dlc(args) -> None:
    q = _query(args)
    with _status("sp_dlc"):
        rows, scanned = engine.dlc_rows(max(args.limit, 40), q.cut_floor(), q.price_cap())
    rows = q.apply(rows)
    ui.section(t("sec_dlc"), "✚", min(args.limit, len(rows)), len(rows))
    if rows:
        ui.dlc_table([{"item": r.item, "owner": _owner(r), "base_name": r.base_name, "hist": r.hist}
                      for r in rows[: args.limit]], show_history=engine.itad.available())
    else:
        ui.empty(t("empty_dlc"))
    _save_last([r.item for r in rows[: args.limit]])
    ui.footer(t("scanned_dlc", n=scanned))


def _owner(r: engine.DlcRow) -> str:
    if r.owner_kind == "you":
        return t("own_you", h=f"{r.hours:.0f}")
    if r.owner_kind == "unplayed":
        return t("own_unplayed")
    return t("own_family", owner=r.owner)


def cmd_info(args) -> None:
    query = " ".join(args.query).strip()
    with _status("sp_lookup"):
        appid = engine.resolve_game(query)
        if not appid:
            ui.error(t("err_not_found", q=query))
            return
        ctx = engine.Context.load()
        rec = engine.game_rec(ctx, appid)
    if not rec:
        ui.error(t("err_not_found", q=query))
        return
    prefs.log_feedback(appid, "info")
    key, params = engine.status_of(ctx, appid)
    ui.info(rec, t(key, **params) if key else "")
    _save_last([rec.item])


def cmd_open(args) -> None:
    last = _load_last()
    if not last:
        ui.error(t("err_no_last"))
        return
    for n in args.numbers:
        if 1 <= n <= len(last):
            appid, name = last[n - 1]
            webbrowser.open(f"https://store.steampowered.com/app/{appid}/")
            prefs.log_feedback(int(appid), "open")
            ui.ok(t("opened", name=name))
        else:
            ui.error(t("err_range", n=n, max=len(last)))


def _resolve_targets(tokens: list[str]) -> list[tuple[int, str]]:
    """'14 15' -> rows from the last list; big numbers -> appids; anything else -> a store search."""
    last = _load_last()
    if all(tok.isdigit() for tok in tokens):
        out = []
        for n in map(int, tokens):
            if 1 <= n <= len(last):
                out.append((int(last[n - 1][0]), last[n - 1][1]))
            elif n > 1000:
                item = get_items([n], with_price=False).get(n)
                out.append((n, item.name if item else f"App {n}"))
            else:
                ui.error(t("err_range", n=n, max=len(last)) if last else t("err_no_last"))
        return out
    hits = store_lookup(" ".join(tokens))
    if not hits:
        ui.error(t("err_not_found", q=" ".join(tokens)))
        return []
    return [hits[0]]


def cmd_hide(args) -> None:
    reason = "owned" if args.owned else "taste"
    for appid, name in _resolve_targets(args.targets):
        prefs.hide(appid, name, reason)
        ui.hidden_ok(name, t("hidden_owned") if reason == "owned" else t("hidden_taste"))
    console.print()


def cmd_unhide(args) -> None:
    if args.targets == ["all"]:
        ui.ok(t("restored_n", n=prefs.clear_hidden()))
        return
    hidden = prefs.load_hidden()
    listed = list(hidden.items())
    for tok in args.targets:
        if tok.isdigit() and 1 <= int(tok) <= len(listed):
            appid, meta = listed[int(tok) - 1]
        elif tok.isdigit() and int(tok) in hidden:
            appid, meta = int(tok), hidden[int(tok)]
        else:
            match = [(a, m) for a, m in listed if tok.lower() in m["name"].lower()]
            if not match:
                ui.error(t("not_hidden", t=tok))
                continue
            appid, meta = match[0]
        prefs.unhide(appid)
        ui.ok(t("restored", name=meta["name"]))


def cmd_target(args) -> None:
    *game, price = args.args if len(args.args) > 1 else (args.args + ["lowest"])
    found = _resolve_targets(game)
    if not found:
        return
    appid, name = found[0]
    if price.lower() in ("off", "remove", "-"):
        prefs.remove_target(appid)
        ui.ok(t("target_removed", name=name))
        return
    if price.lower() in ("lowest", "low", "atl", "рекорд"):
        prefs.set_target(appid, name, None)
        ui.ok(t("target_lowest", name=name))
        return
    try:
        value = reg._budget(price)
    except reg.SettingError as e:
        ui.error(str(e))
        return
    prefs.set_target(appid, name, round(value * 100))
    ui.ok(t("target_set", name=name, price=ui.money(value)))


def cmd_targets(args) -> None:
    rows = []
    for appid, tg in prefs.targets().items():
        want = t("target_any_low") if tg["price_cents"] is None else region.price_format(cfg().country).format(
            tg["price_cents"])
        rows.append([str(len(rows) + 1), tg["name"], want])
    ui.simple_table(["#", t("col_game"), t("target_col")], rows, t("sec_targets"), "🎯")
    ui.plain("  " + t("target_hint"), "grey42")
    console.print()


def cmd_calendar(args) -> None:
    from . import calendar
    from .notify.cards import sale_name
    with _status("sp_calendar"):
        evs = calendar.events()
        taste = []
        if ready(quiet=True):
            taste = [x for x, _ in engine.Context.load().profile.top_tags(5)]
    today = dt.date.today()
    want = {x.lower() for x in taste}
    rows = []
    for e in evs:
        if e.end < today:
            continue
        mine = bool(want & {x.lower() for x in e.tags})
        name = sale_name(e.name) if e.kind == "sale" else e.name
        style = "bold #ff8a3d" if e.kind == "sale" else (ui.ACCENT if mine else "")
        when = f"{day_month(e.start)} – {day_month(e.end)}"
        rel = t("cal_now") if e.start <= today else t("cal_in_days", n=(e.start - today).days)
        rows.append([Text("🔥" if e.kind == "sale" else ("★" if mine else "·")), Text(name, style=style), when,
                     Text(rel, style="grey50")])
    ui.simple_table(["", t("cal_event"), t("cal_dates"), ""], rows, t("sec_calendar"), "📅")
    ui.plain("  " + t("cal_source"), "grey42")
    console.print()


def cmd_dna(args) -> None:
    with _status("sp_dna"):
        ctx = engine.Context.load()        # same tag space as the main list → same taste everywhere
    ui.header(ctx.lib, ctx.profile, len(ctx.hidden), engine.itad.available(), len(ctx.family_shared))
    _privacy(ctx)
    ui.dna(ctx.profile, ctx.lib)


def cmd_family(args) -> None:
    from .steam import load_library, split_family
    with _status("sp_family"):
        lib = load_library()
        meta = get_items(list(lib.family_games), with_price=False) if lib.family_games else {}
        unshared = len(split_family(lib.family_games, meta)[1])
    ui.family(lib, unshared)


def cmd_doctor(args) -> int:
    from . import doctor
    with _status("sp_doctor"):
        checks = doctor.run_checks()
    ui.section(t("sec_doctor"), "✚")
    icons = {"ok": ("✓", "green"), "info": ("·", "grey62"), "warn": ("!", "yellow"), "fail": ("✗", "bold red")}
    for ch in checks:
        icon, style = icons[ch.status]
        line = Text(f"  {icon} ", style=style)
        line.append(f"{ch.title:<22}", style="bold" if ch.status != "info" else "grey62")
        line.append(ch.detail, style="grey62")
        console.print(line)
        if ch.fix and ch.status in ("warn", "fail", "info"):
            console.print(Text(f"      → {ch.fix}", style="grey50"))
    ok, warn, fail = doctor.summary(checks)
    console.print()
    ui.plain(f"  {t('dr_summary', ok=ok, warn=warn, fail=fail)}", "bold green" if not fail else "bold red")
    console.print()
    return 1 if fail else 0


# --------------------------------------------------------------------------- config & profiles

def cmd_config(args) -> None:
    action = args.action or "show"
    if action == "show":
        rows = []
        c = cfg()
        rows.append(("profile", Text(c.profile_name, style="magenta")))
        for s in reg.REGISTRY:
            if args.all or s.where in ("profile", "settings", "secret") and s.key not in (
                    "smtp-password", "discord-webhook", "telegram-token"):
                val = reg.show(s.key)
                rows.append((s.key, Text(val, style="red" if val in ("—",) and s.key in ("steam", "country",
                                                                                         "steam-key") else "")))
        ui.kv_table(rows, t("sec_config"))
        ui.plain(f"  {t('cfg_more')}  ·  {CONFIG_FILE}  ·  {DB_FILE}", "grey42")
        console.print()
    elif action == "set":
        if not args.rest:
            ui.error(t("cfg_unknown_key", k="", keys=", ".join(reg.BY_KEY)))
            return
        key, raw = args.rest[0].lower(), " ".join(args.rest[1:]).strip()
        if key in reg.SECRET_KEYS and not raw:
            raw = getpass.getpass(f"  {t('cfg_key_prompt')}").strip()
        if key == "steam-key" and raw:
            from .doctor import check_steam_key
            if check_steam_key(raw) is False:
                ui.error(t("cfg_key_invalid"))
                return
        if key == "itad-key" and raw:
            from .doctor import check_itad_key
            if check_itad_key(raw) is False:
                ui.error(t("cfg_itad_invalid"))
                return
        try:
            with _status("sp_resolve"):
                value = reg.apply(key, raw)
        except reg.SettingError as e:
            ui.error(str(e))
            return
        cfg().settings.save()
        if key in reg.SECRET_KEYS:
            ui.ok(t("cfg_key_saved", where=value))
        elif key == "steam":
            from .steam import get_player_summaries
            name = get_player_summaries([value]).get(value, {}).get("name", "") if cfg().steam_api_key else ""
            ui.ok(t("cfg_profile_set", name=name or "?", id=value))
        else:
            ui.ok(f"{key}: {reg.show(key)}")
    elif action == "regions":
        _regions(" ".join(args.rest or []))
    elif action == "clear-cache":
        ui.ok(t("cfg_cache_cleared", n=clear_cache()))
    elif action == "help":
        rows = [(s.key, Text(t(s.help_key), style="grey62")) for s in reg.REGISTRY]
        ui.kv_table(rows, t("sec_config_keys"))
        console.print()


def _regions(query: str) -> None:
    c = cfg()
    codes = region.search(query, c.lang) if query else [k for k, v in region._data().items()
                                                        if v.get("group") and v["group"] != "USD"]
    rows = []
    for code in codes:
        i = region.info(code) or {}
        if i.get("store"):
            rows.append([code, region.name(code, c.lang), i.get("group") or region.currency_marker(code),
                         i["sample"][0] if i.get("sample") else ""])
    rows.sort(key=lambda r: (r[2], r[1]))
    ui.simple_table([t("col_code"), t("col_country"), t("col_currency"), t("col_example")], rows, t("sec_regions"))
    ui.plain("  " + t("regions_hint") + "  sift config regions <name>", "grey42")
    console.print()


def cmd_profile(args) -> None:
    s = cfg().settings
    action, name = args.action or "list", (args.name or "").strip()
    if action == "add" and name:
        s.profiles.setdefault(name, Profile(country=cfg().country))
        s.save()
        ui.ok(t("pf_created", name=name))
    elif action == "use" and name:
        if name not in s.profiles:
            ui.error(t("pf_unknown", name=name))
            return
        s.active = name
        s.save()
        ui.ok(t("pf_active", name=name))
    elif action == "remove" and name:
        if name not in s.profiles:
            ui.error(t("pf_unknown", name=name))
        elif len(s.profiles) == 1:
            ui.error(t("pf_last"))
        else:
            del s.profiles[name]
            if s.active == name:
                s.active = next(iter(s.profiles))
            s.save()
            ui.ok(t("pf_removed", name=name))
    else:
        rows = [[("● " if n == s.active else "  ") + n, p.steam_id or "—",
                 region.label(p.country, cfg().lang) if p.country else "—"] for n, p in s.profiles.items()]
        ui.simple_table(["", "steam", t("col_country")], rows, t("sec_profiles"))
        console.print()


# --------------------------------------------------------------------------- notifications

def cmd_notify(args) -> int:
    from .notify import runner
    c = cfg()
    n = c.profile.notify
    action = args.action or "status"
    if action == "status":
        installed, detail = schedule.status(c.profile_name)
        rows = [
            (t("n_channels"), ", ".join(n.channels) or t("n_none")),
            (t("n_mode"), f"{n.mode}" + (f" · {n.digest_time}" if n.mode == "digest" else "")),
            (t("n_quiet"), n.quiet or "—"),
            (t("n_events"), ", ".join(n.events)),
            (t("n_schedule"), (f"✓ {detail}" if installed else t("dr_schedule_off"))),
        ]
        if n.paused_until > time.time():
            rows.append((t("n_paused"), day_month(dt.date.fromtimestamp(n.paused_until))))
        from .notify.events import pending_count
        rows.append((t("n_pending"), str(pending_count(c.profile_name))))
        ui.kv_table(rows, t("sec_notify"), "🔔")
        ui.plain("  " + t("n_hint"), "grey42")
        console.print()
    elif action == "setup":
        return _notify_setup(args.value or "telegram")
    elif action == "test":
        with _status("sp_test"):
            card, errors = runner.send_test([args.value] if args.value else None)
        if card:
            ui.ok(t("n_test_sent", name=card.title, channels=", ".join([args.value] if args.value else n.channels)))
        for e in errors:
            ui.error(e)
        return 1 if errors else 0
    elif action == "run":
        if not ready(quiet=True):
            ui.error(t("err_not_configured"))
            return 1
        rep = runner.run(dry_run=args.dry_run, force_digest=args.digest_now)
        if rep.skipped:
            ui.warn(t(f"n_skipped_{rep.skipped}"))
            return 0
        if args.dry_run:
            for e in rep.events:
                ui.plain(f"  {e.card.icon} {e.kind:<12} {e.card.title}  {e.card.price}  {e.card.verdict}", "")
            ui.plain(f"  {t('n_dry', n=len(rep.events))}", "grey50")
        else:
            ui.ok(t("n_ran", events=len(rep.events), sent=rep.sent, queued=rep.queued, digest=rep.digest_sent))
        for e in rep.errors:
            ui.error(e)
        return 1 if rep.errors else 0
    elif action == "enable":
        every = args.every or n.every
        n.every = every
        c.settings.save()
        ok, detail = schedule.enable(c.profile_name, every)
        (ui.ok if ok else ui.error)(t("n_enabled", every=every) if ok else f"{t('n_enable_failed')}: {detail}")
        return 0 if ok else 1
    elif action == "disable":
        ok, _ = schedule.disable(c.profile_name)
        ui.ok(t("n_disabled")) if ok else ui.warn(t("dr_schedule_off"))
    elif action == "pause":
        days = int(args.value or 7)
        n.paused_until = int(time.time() + days * 86400)
        c.settings.save()
        ui.ok(t("tg_paused", n=days))
    elif action == "resume":
        n.paused_until = 0
        c.settings.save()
        ui.ok(t("tg_resumed"))
    elif action == "actions":
        target = os.path.abspath(args.value or "sift-actions")
        path = os.path.join(target, ".github", "workflows", "sift.yml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(schedule.actions_workflow(n.every, c.lang))
        ui.ok(t("n_actions_written", path=path))
        ui.plain(t("n_actions_secrets"), "grey62")
        for name, val in (("STEAM_ID64", c.steam_id), ("STEAM_COUNTRY", c.country),
                          ("STEAM_API_KEY", "•••" if c.steam_api_key else ""),
                          ("ITAD_API_KEY", "•••" if c.itad_api_key else ""),
                          ("SIFT_FAMILY", ",".join(c.family or _client_family_ids())),
                          ("SIFT_TELEGRAM_TOKEN", "•••" if get_secret("telegram_token") else ""),
                          ("SIFT_TELEGRAM_CHAT", n.telegram_chat), ("SIFT_NTFY_TOPIC", n.ntfy_topic)):
            if val:
                ui.plain(f"    {name:<22} {val}", "")
        console.print()
    return 0


def _client_family_ids() -> list[str]:
    from .localsteam import family_from_client
    return [x for x in family_from_client(cfg().steam_id).get("member_steam_ids", []) if x != cfg().steam_id]


def _notify_setup(channel: str) -> int:
    """Interactive channel setup in the terminal (the wizard offers the same in its UI)."""
    from .notify.channels import ChannelError
    from .notify.runner import send_test
    c = cfg()
    n = c.profile.notify
    channel = channel.lower()
    try:
        if channel == "telegram":
            from .notify.telegram import Telegram, TelegramError, wait_for_start
            ui.plain(t("tg_setup_1"), "")
            webbrowser.open("https://t.me/BotFather")
            token = getpass.getpass(f"  {t('tg_token_prompt')}").strip()
            try:
                me = Telegram(token).get_me()
            except TelegramError as e:
                ui.error(f"{t('tg_token_bad')} ({e})")
                return 1
            ui.ok(t("tg_bot_ok", bot=me["username"]))
            ui.plain(t("tg_setup_2", bot=me["username"]), "")
            webbrowser.open(f"https://t.me/{me['username']}")
            tg = Telegram(token)
            with console.status(f"[grey50]{t('tg_waiting')}", spinner="dots"):
                found = wait_for_start(tg, timeout=240)
            if not found:
                ui.error(t("tg_no_start"))
                return 1
            set_secret("telegram_token", token)
            n.telegram_chat = found["chat_id"]
            tg.chat_id = found["chat_id"]
            tg.set_commands()
            ui.ok(t("tg_linked", name=found["name"] or found["chat_id"]))
        elif channel == "discord":
            ui.plain(t("dc_setup"), "")
            hook = getpass.getpass(f"  {t('dc_prompt')}").strip()
            from .net import SESSION
            if not hook.startswith("https://") or SESSION.get(hook, timeout=10).status_code != 200:
                ui.error(t("dc_bad"))
                return 1
            set_secret("discord_webhook", hook)
        elif channel == "ntfy":
            topic = n.ntfy_topic or f"sift-{secrets.token_hex(5)}"
            n.ntfy_topic = topic
            ui.plain(t("ntfy_setup", url=f"{n.ntfy_server.rstrip('/')}/{topic}"), "")
        elif channel == "email":
            n.smtp_host = input(f"  SMTP host [{n.smtp_host or 'smtp.gmail.com'}]: ").strip() or n.smtp_host or "smtp.gmail.com"
            port = input(f"  SMTP port [{n.smtp_port}]: ").strip()
            n.smtp_port = int(port) if port else n.smtp_port
            n.smtp_user = input(f"  SMTP user [{n.smtp_user}]: ").strip() or n.smtp_user
            set_secret("smtp_password", getpass.getpass("  SMTP password / app password: "))
            n.email_to = input(f"  {t('email_to_prompt')} [{n.email_to or n.smtp_user}]: ").strip() or n.email_to or n.smtp_user
        elif channel != "desktop":
            ui.error(t("set_choice", opts="telegram | discord | ntfy | desktop | email"))
            return 1
        if channel not in n.channels:
            n.channels.append(channel)
        c.settings.save()
        with _status("sp_test"):
            card, errors = send_test([channel])
        for e in errors:
            ui.error(e)
        if card and not errors:
            ui.ok(t("n_test_sent", name=card.title, channels=channel))
        installed, _ = schedule.status(c.profile_name)
        if not installed:
            ui.plain("  " + t("n_offer_enable"), "grey62")
        return 1 if errors else 0
    except (ChannelError, KeyboardInterrupt, EOFError):
        console.print()
        return 1


def cmd_watch(args) -> int:
    every = args.every or cfg().profile.notify.every
    ui.ok(t("watch_start", every=every))

    def report(rep):
        stamp = time.strftime("%H:%M")
        ui.plain(f"  {stamp}  " + t("n_ran", events=len(rep.events), sent=rep.sent, queued=rep.queued,
                                     digest=rep.digest_sent), "grey50")
        for e in rep.errors:
            ui.error(e)
    try:
        schedule.watch(every, on_report=report)
    except KeyboardInterrupt:
        console.print()
    return 0


def cmd_setup(args) -> int:
    from .tui.wizard import run_wizard
    result = run_wizard()
    if result == "show" and ready(quiet=True):
        return cmd_app(args)
    return 0


def cmd_app(args) -> int:
    """The full-screen app — what plain `sift` opens in a terminal."""
    if not ready(quiet=True):
        from .tui.wizard import run_wizard
        if run_wizard() != "show" or not ready():
            return 1
    from .tui.app import run_app
    run_app(_query(args))
    return 0


# --------------------------------------------------------------------------- macros

def cmd_macro(rest: list[str], reserved: set[str]) -> int:
    action = rest[0].lower() if rest else "list"
    if action in ("list", "ls"):
        macros = sorted(query.all_macros().items(), key=lambda kv: (kv[1][1], kv[0]))
        ui.section(t("sec_macros"), "⚡", len(macros), len(macros))
        width = max(len(n) for n, _ in macros) + 3
        for name, (flags, builtin) in macros:
            try:
                what = describe(query.parse(flags))
            except query.QueryError as e:
                what = f"✗ {e}"
            line = Text("  ")
            line.append(f"{name:<{width}}", style="bold" if builtin else "bold magenta")
            line.append(what)
            console.print(line)
            sub = Text(" " * (width + 2) + f"{flags}", style="grey42")
            if builtin:
                sub.append(f"  · {t('m_builtin')}", style="grey35")
            console.print(sub)
        console.print()
        ui.plain("  " + t("m_hint"), "grey42")
        console.print()
        return 0
    if action in ("add", "set", "save", "new") and len(rest) >= 2:
        name, flags = rest[1].lower(), shlex.join(rest[2:])
        if not flags:
            ui.error(t("m_need_flags", name=name))
            return 2
        try:
            q = query.save_macro(name, flags, reserved)
        except query.QueryError as e:
            ui.error(str(e))
            return 2
        ui.ok(t("m_saved", name=name))
        ui.plain(f"  {describe(q)}", "grey62")
        return 0
    if action in ("rm", "remove", "del", "delete") and len(rest) >= 2:
        name = rest[1].lower()
        if query.remove_macro(name):
            ui.ok(t("m_removed", name=name))
            return 0
        ui.error(t("m_builtin_rm", name=name) if name in query.BUILTIN_MACROS else t("m_unknown", name=name))
        return 1
    ui.plain("  " + t("m_hint"), "grey62")
    return 2


# --------------------------------------------------------------------------- argparse

def common(parser: argparse.ArgumentParser, top: bool = False) -> None:
    """Options accepted both before and after a command (sub-parsers use SUPPRESS to not clobber)."""
    d = (lambda v: v) if top else (lambda v: argparse.SUPPRESS)
    parser.add_argument("-b", "--budget", type=float, default=d(None), help="max price in your store's currency")
    parser.add_argument("-d", "--min-discount", type=int, default=d(None), metavar="PCT", help="min discount %%")
    parser.add_argument("-l", "--limit", type=int, default=d(12), help="rows per section (default 12)")
    parser.add_argument("-r", "--refresh", action="store_true", default=d(False), help="ignore cached prices & library")
    parser.add_argument("-p", "--profile", default=d(None), help="settings profile to use")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sift", description="Steam deals, sifted: every discount checked against two years of prices (HOT · GREAT · OK · MEH · NOPE).",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n", 2)[2])
    query.add_view_args(p)
    common(p, top=True)
    p.add_argument("-P", "--print", action="store_true", help="print a table instead of opening the app")
    p.add_argument("-J", "--json", action="store_true", help="print deals as JSON")
    p.add_argument("--dna", "--taste", action="store_true", dest="dna", help=argparse.SUPPRESS)
    p.add_argument("-V", "--version", action="version", version=f"sift {__version__}")

    sub = p.add_subparsers(dest="cmd", metavar="command")

    def add(name, help_, **kw):
        sp = sub.add_parser(name, help=help_, **kw)
        common(sp)
        return sp

    add("macro", "saved filters: list | add <name> <flags> | rm <name>  →  sift <name>").add_argument(
        "rest", nargs=argparse.REMAINDER)
    add("setup", "guided first-time setup")
    add("doctor", "check keys, privacy, region, family, notifications")
    add("dlc", "discounted DLC for games you or your family own")
    add("info", "price, history & match for one game").add_argument("query", nargs="+", help="title or appid")
    add("open", "open result #N from the last list").add_argument("numbers", nargs="+", type=int)
    add("dna", "your taste profile")
    add("family", "your Steam Family")
    add("calendar", "Steam seasonal sales & themed fests")
    hd = add("hide", "⊘ don't recommend: sift hide 14 15 | sift hide \"game name\"")
    hd.add_argument("targets", nargs="+", help="row numbers from the last list, appids, or a title")
    hd.add_argument("--owned", action="store_true", help="have it elsewhere: exclude without lowering similar games")
    add("unhide", "restore hidden games: sift unhide 2 | sift unhide all").add_argument("targets", nargs="+")
    add("hidden", "list games you've hidden")
    add("target", "price alert: sift target 3 9.99 | sift target \"elden ring\" lowest | … off").add_argument(
        "args", nargs="+")
    add("targets", "list your price targets")
    cf_ = add("config", "show / change settings: sift config set country KZ · sift config help")
    cf_.add_argument("action", nargs="?", choices=["show", "set", "regions", "clear-cache", "help"], default="show")
    cf_.add_argument("rest", nargs="*")
    cf_.add_argument("--all", action="store_true", help="show every setting")
    pf = add("profile", "profiles: list | add <name> | use <name> | remove <name>")
    pf.add_argument("action", nargs="?", choices=["list", "add", "use", "remove"], default="list")
    pf.add_argument("name", nargs="?")
    nt = add("notify", "alerts: status | setup <telegram|discord|ntfy|desktop|email> | test | run | enable | "
                       "disable | pause <days> | resume | actions [dir]")
    nt.add_argument("action", nargs="?", default="status",
                    choices=["status", "setup", "test", "run", "enable", "disable", "pause", "resume", "actions"])
    nt.add_argument("value", nargs="?")
    nt.add_argument("--dry-run", action="store_true", help="show what would be sent")
    nt.add_argument("--digest-now", action="store_true", help="send the queued digest immediately")
    nt.add_argument("--every", type=int, help="minutes between scans (enable)")
    wt = add("watch", "keep running: scan every N minutes, Telegram buttons react instantly")
    wt.add_argument("--every", type=int)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["help"]:
        argv = ["--help", *argv[1:]] if len(argv) == 1 else [*argv[1:], "--help"]   # sift help [command]
    parser = build_parser()
    commands = set(next(a.choices for a in parser._actions if isinstance(a, argparse._SubParsersAction)))
    takes_value = {o for a in parser._actions for o in a.option_strings if a.nargs != 0}
    config.activate(_peek_profile(argv))
    if argv[:1] in (["macro"], ["macros"]):
        return cmd_macro(argv[1:], commands | {"help", "macros"})
    argv, used = query.expand(argv, commands, takes_value)
    first = next((x for i, x in enumerate(argv) if not x.startswith("-")
                  and not (i and argv[i - 1] in takes_value)), None)
    if first and first not in commands:
        import difflib
        close = difflib.get_close_matches(first, list(commands) + list(query.all_macros()), n=1, cutoff=0.6)
        ui.error(t("err_unknown_cmd", cmd=first) + (f"  →  sift {close[0]}" if close else ""))
        ui.plain("  " + t("hint_help") + "  ·  sift macro", "grey50")
        return 2
    args = parser.parse_args(argv)
    c = config.activate(args.profile)
    set_refresh(args.refresh)
    if args.cmd is None:
        try:
            args.query = query.from_args(args)
        except query.QueryError as e:
            ui.error(str(e))
            return 2
        args.query.macros = used
    if args.budget is not None and args.cmd is not None:     # plain `sift`: the query owns it (shown as a chip)
        c.budget = args.budget if args.budget > 0 else None
    if args.min_discount is None:
        args.min_discount = c.min_discount

    first_run = not CONFIG_FILE.exists() and args.cmd is None and sys.stdin.isatty() and sys.stdout.isatty()
    no_setup = {"config", "profile", "open", "unhide", "hidden", "setup", "doctor", "targets", "calendar"}
    try:
        if first_run and not ready(quiet=True):
            return cmd_setup(args) or 0
        if args.cmd in no_setup or (args.cmd == "notify" and args.action in ("status", "setup", "pause", "resume",
                                                                            "disable", "actions")):
            handler = {"config": cmd_config, "profile": cmd_profile, "open": cmd_open, "unhide": cmd_unhide,
                       "hidden": lambda a: ui.hidden_list(prefs.load_hidden()), "setup": cmd_setup,
                       "doctor": cmd_doctor, "targets": cmd_targets, "calendar": cmd_calendar,
                       "notify": cmd_notify}[args.cmd]
            return handler(args) or 0
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
        if args.cmd is None and not (args.dna or args.print or getattr(args, "json", False)) and interactive:
            return cmd_app(args)
        if not ready():
            return 1
        handler = {"dlc": cmd_dlc, "hide": cmd_hide, "info": cmd_info, "dna": cmd_dna, "family": cmd_family,
                   "target": cmd_target, "notify": cmd_notify, "watch": cmd_watch}.get(args.cmd)
        if args.dna:
            handler = cmd_dna
        return (handler or cmd_deals)(args) or 0
    except KeyboardInterrupt:
        console.print()
        return 130


def _peek_profile(argv: list[str]) -> str | None:
    """-p / --profile before argparse runs (macros are read from the active settings first)."""
    for i, tok in enumerate(argv):
        if tok in ("-p", "--profile") and i + 1 < len(argv):
            return argv[i + 1]
        if tok.startswith("--profile="):
            return tok.split("=", 1)[1]
    return None


def entry() -> None:
    sys.exit(main())


if __name__ == "__main__":
    entry()
