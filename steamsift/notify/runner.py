"""`sift notify run`: scan, detect events, deliver now or queue for the digest; Telegram bot commands."""
from __future__ import annotations

import datetime as dt
import html
import time
from dataclasses import dataclass, field

from .. import config, engine, prefs, region
from ..config import get_secret
from ..db import Cache
from ..i18n import num, review_label, t
from . import events as ev
from .cards import Card
from .channels import ChannelError, desktop_send, discord_send, email_send, ntfy_send
from .telegram import Telegram, TelegramError, handle_updates

_state = Cache("notify")
CHANNELS = ("telegram", "discord", "ntfy", "desktop", "email")


@dataclass
class Report:
    events: list[ev.Event] = field(default_factory=list)
    sent: int = 0
    queued: int = 0
    digest_sent: int = 0
    errors: list[str] = field(default_factory=list)
    skipped: str = ""          # why nothing ran (paused / no channels)


def cfg() -> config.Runtime:
    return config.cfg


def telegram() -> Telegram | None:
    token, chat = get_secret("telegram_token"), cfg().profile.notify.telegram_chat
    return Telegram(token, chat) if token and chat else None


def active_channels() -> list[str]:
    return [c for c in cfg().profile.notify.channels if c in CHANNELS]


def deliver(cards: list[Card], title: str, as_digest: bool, channels: list[str] | None = None) -> list[str]:
    """Send to every configured channel; returns error strings (one failing channel never blocks the others)."""
    n = cfg().profile.notify
    errors = []
    for ch in channels or active_channels():
        try:
            if ch == "telegram":
                tg = telegram()
                if not tg:
                    raise ChannelError("telegram: run `sift notify setup telegram`")
                if as_digest and len(cards) > 2:
                    tg.send_digest(cards, title)
                else:
                    for c in cards:
                        tg.send_card(c)
            elif ch == "discord":
                hook = get_secret("discord_webhook")
                if not hook:
                    raise ChannelError("discord: no webhook")
                discord_send(hook, cards, title if as_digest else "")
            elif ch == "ntfy":
                if not n.ntfy_topic:
                    raise ChannelError("ntfy: no topic")
                ntfy_send(n.ntfy_server, n.ntfy_topic, cards, get_secret("ntfy_token"))
            elif ch == "desktop":
                desktop_send(cards, title)
            elif ch == "email":
                if not (n.smtp_host and n.email_to):
                    raise ChannelError("email: smtp host / recipient missing")
                email_send(n.smtp_host, n.smtp_port, n.smtp_user, get_secret("smtp_password"), n.email_to, cards,
                           title)
        except (ChannelError, TelegramError) as e:
            errors.append(str(e))
    return errors


def process_telegram() -> int:
    """Apply pending button presses / commands (works without a long-running bot: done at each scan)."""
    tg = telegram()
    if not tg:
        return 0
    key = f"{cfg().profile_name}:tg_offset"
    offset = _state.get(key) or 0
    updates = tg.poll(offset, 0)
    if not updates:
        return 0
    new_offset = handle_updates(tg, updates, lambda cmd, arg: answer_command(tg, cmd, arg))
    _state.set(key, max(offset, new_offset))
    _state.flush()
    return len(updates)


def run(dry_run: bool = False, now: float | None = None, digest=None, dlc=None, force_digest: bool = False) -> Report:
    c = cfg()
    n = c.profile.notify
    now = now or time.time()
    rep = Report()
    if n.paused_until > now:
        rep.skipped = "paused"
        return rep
    if not active_channels() and not dry_run:
        rep.skipped = "no_channels"
        return rep
    if not dry_run:
        process_telegram()

    if digest is None:
        ctx = engine.Context.load()
        digest = engine.build_digest(ctx, limit=20)
    if dlc is None and "dlc_lowest" in n.events:
        dlc = engine.dlc_rows(limit=20)[0]

    found = ev.fresh(ev.detect(digest, dlc, n, now), c.profile_name, now)
    rep.events = found
    if dry_run:
        return rep

    local = dt.datetime.fromtimestamp(now)
    quiet = ev.in_quiet(n.quiet, local)
    if n.mode == "instant" and not quiet:
        cards = [e.card for e in found]
        if cards:
            burst, rest = cards[: n.max_cards], cards[n.max_cards:]
            rep.errors += deliver(burst, ev.digest_title(burst), as_digest=False)
            if rest:
                rep.errors += deliver(rest, ev.digest_title(rest), as_digest=True)
            rep.sent = len(cards)
        held = ev.take_pending(c.profile_name)            # alerts held during quiet hours
        if held:
            rep.errors += deliver(held, ev.digest_title(held), as_digest=True)
            rep.digest_sent = len(held)
    else:
        ev.enqueue(found, c.profile_name, now)
        rep.queued = len(found)
        last = _state.get(f"{c.profile_name}:last_digest") or 0
        if n.mode == "digest" and not quiet and (force_digest or ev.digest_due(n.digest_time, local, last)):
            cards = ev.take_pending(c.profile_name)
            if cards:
                rep.errors += deliver(cards, ev.digest_title(cards), as_digest=True)
                rep.digest_sent = len(cards)
            _state.set(f"{c.profile_name}:last_digest", now)
    ev.mark(found, c.profile_name, now)
    _state.flush()
    return rep


def send_test(channels: list[str] | None = None) -> tuple[Card | None, list[str]]:
    """One real card from your current picks, sent to the given (or all configured) channels."""
    ctx = engine.Context.load()
    d = engine.build_digest(ctx, limit=5)
    recs = d.wish[:1] or d.picks[:1]
    if not recs:
        return None, ["no deals to show right now"]
    card = Card.from_rec(recs[0], "wish_lowest" if recs[0].is_wish else "pick_strong")
    card.notes = ("🧪 " + t("test_note") + (" · " + card.notes if card.notes else ""))
    return card, deliver([card], t("test_title"), as_digest=False, channels=channels)


# --------------------------------------------------------------------------- bot commands & info

def info_text(appid: int) -> str:
    e = html.escape
    ctx = engine.Context.load(with_pool=False)
    rec = engine.game_rec(ctx, appid)
    if not rec:
        return e(t("err_not_found", q=appid))
    i = rec.item
    lines = [f"<b><a href=\"{i.url}\">{e(i.name)}</a></b>"]
    key, params = engine.status_of(ctx, appid)
    if key:
        lines.append(f"<i>{e(t(key, **params))}</i>")
    if not i.available:
        lines.append(e(t("st_unavailable", country=engine.country_name())))
    elif i.purchasable:
        price = f"<b>{e(i.final_fmt)}</b>" + (f"  <s>{e(i.orig_fmt)}</s>  −{i.cut}%" if i.cut else "")
        lines.append(price)
    if rec.hist:
        lines.append(e(t("deepest", n=rec.hist.best_cut)))
    if i.review_count:
        lines.append(e(f"{review_label(i.review_label)} · {t('reviews_of', pct=i.review_pct, n=num(i.review_count))}"))
    lines.append(e(f"{t('match')}: {rec.score:.0f} · {rec.why}"))
    from .cards import notes_for
    notes = notes_for(rec)
    if notes:
        lines.append(f"<i>{e(notes)}</i>")
    return "\n".join(lines)


def answer_command(tg: Telegram, cmd: str, arg: str) -> None:
    c = cfg()
    p = c.profile
    try:
        if cmd in ("start", "help"):
            tg.send_text(t("tg_help"))
        elif cmd in ("top", "wishlist"):
            d = engine.build_digest(engine.Context.load(), limit=5)
            recs = (d.wish if cmd == "wishlist" else d.picks)[:5]
            if not recs:
                tg.send_text(t("empty_wish") if cmd == "wishlist" else t("empty_picks"))
            for r in recs:
                tg.send_card(Card.from_rec(r, "wish_lowest" if r.is_wish else "top"))
        elif cmd == "dlc":
            rows = engine.dlc_rows(limit=8)[0][:8]
            tg.send_digest([Card.from_dlc(r) for r in rows], t("sec_dlc").upper()) if rows else \
                tg.send_text(t("empty_dlc"))
        elif cmd == "info":
            appid = engine.resolve_game(arg) if arg else None
            tg.send_text(info_text(appid) if appid else t("tg_info_usage"))
        elif cmd == "hidden":
            hidden = prefs.load_hidden()
            tg.send_text("\n".join(f"⊘ {html.escape(h['name'])}" for h in hidden.values()) or t("empty_hidden"))
        elif cmd == "budget":
            if arg.lower() in ("off", "0", "-"):
                p.budget = None
            else:
                p.budget = float(arg.replace(",", ".").replace(" ", ""))
            c.settings.save()
            tg.send_text(t("cfg_budget_set", v=region.price_format(c.country).amount(p.budget))
                         if p.budget else t("cfg_budget_off"))
        elif cmd == "pause":
            days = int(arg or 7)
            p.notify.paused_until = int(time.time() + days * 86400)
            c.settings.save()
            tg.send_text(t("tg_paused", n=days))
        elif cmd == "resume":
            p.notify.paused_until = 0
            c.settings.save()
            tg.send_text(t("tg_resumed"))
        else:
            tg.send_text(t("tg_help"))
    except (ValueError, TelegramError) as e:
        try:
            tg.send_text(f"✗ {html.escape(str(e))}")
        except TelegramError:
            pass
