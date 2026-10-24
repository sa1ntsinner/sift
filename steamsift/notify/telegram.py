"""Personal Telegram bot: cards with cover art and buttons, digests, commands, ⊘ hide from the chat."""
from __future__ import annotations

import time
from typing import Any

import requests

from .. import prefs
from ..i18n import t
from ..net import SESSION
from .cards import Card, sale_name, telegram_caption

API = "https://api.telegram.org"


class TelegramError(RuntimeError):
    pass


class Telegram:
    def __init__(self, token: str, chat_id: str | int | None = None, session: requests.Session | None = None):
        self.token = token.strip()
        self.chat_id = str(chat_id) if chat_id else ""
        self.s = session or SESSION

    # ---------------------------------------------------------------- transport

    def call(self, method: str, timeout: int = 20, **params) -> Any:
        try:
            r = self.s.post(f"{API}/bot{self.token}/{method}", json=params, timeout=timeout)
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            raise TelegramError(f"{method}: {type(e).__name__}") from None
        if not data.get("ok"):
            raise TelegramError(f"{method}: {data.get('description', r.status_code)}")
        return data.get("result")

    def get_me(self) -> dict:
        return self.call("getMe")

    def poll(self, offset: int = 0, wait: int = 0) -> list[dict]:
        """getUpdates; `wait` is Telegram's long-poll timeout (kept apart from the HTTP timeout)."""
        try:
            r = self.s.post(f"{API}/bot{self.token}/getUpdates", timeout=wait + 15,
                            json={"offset": offset, "timeout": wait, "allowed_updates": ["message", "callback_query"]})
            data = r.json()
        except (requests.RequestException, ValueError):
            return []
        return data.get("result", []) if data.get("ok") else []

    # ---------------------------------------------------------------- messages

    def send_text(self, text: str, buttons: list[list[dict]] | None = None, chat_id: str | None = None) -> dict:
        params = {"chat_id": chat_id or self.chat_id, "text": text[:4096], "parse_mode": "HTML",
                  "link_preview_options": {"is_disabled": True}}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        return self.call("sendMessage", **params)

    def send_card(self, card: Card) -> dict:
        caption = telegram_caption(card)
        try:
            return self.call("sendPhoto", chat_id=self.chat_id, photo=card.image, caption=caption,
                             parse_mode="HTML", reply_markup={"inline_keyboard": card_keyboard(card.appid, card.url)})
        except TelegramError:
            # Telegram couldn't fetch the cover — send the same card as text
            return self.send_text(caption, card_keyboard(card.appid, card.url))

    def send_digest(self, cards: list[Card], title: str) -> None:
        """Album of covers + one numbered list with ⊘ buttons (albums can't carry buttons)."""
        if not cards:
            return
        media = [{"type": "photo", "media": c.image} for c in cards[:10]]
        media[0]["caption"] = f"<b>{title}</b>"
        media[0]["parse_mode"] = "HTML"
        try:
            if len(media) >= 2:
                self.call("sendMediaGroup", chat_id=self.chat_id, media=media)
        except TelegramError:
            pass
        lines, row, rows = [f"<b>{title}</b>", ""], [], []
        for n, c in enumerate(cards[:20], 1):
            price = f"{c.price} −{c.cut}%" if c.cut else c.price
            extra = f" · {c.verdict}" if c.verdict else ""
            lines.append(f"{n}. {c.icon} <a href=\"{c.url}\">{escape(c.title)}</a> — <b>{escape(price)}</b>{escape(extra)}")
            if c.why:
                lines.append(f"    <i>{escape(c.why[:90])}</i>")
            row.append({"text": f"⊘ {n}", "callback_data": f"h:{c.appid}"})
            if len(row) == 5:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        self.send_text("\n".join(lines), rows)

    def edit_markup(self, chat_id, message_id, buttons: list[list[dict]] | None) -> None:
        try:
            self.call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
                      reply_markup={"inline_keyboard": buttons or []})
        except TelegramError:
            pass

    def answer(self, callback_id: str, text: str = "") -> None:
        try:
            self.call("answerCallbackQuery", callback_query_id=callback_id, text=text[:190])
        except TelegramError:
            pass

    def set_commands(self) -> None:
        cmds = [{"command": c, "description": t(f"tg_cmd_{c}")}
                for c in ("top", "wishlist", "dlc", "info", "hidden", "budget", "pause", "resume", "help")]
        try:
            self.call("setMyCommands", commands=cmds)
        except TelegramError:
            pass


def escape(s: str) -> str:
    import html
    return html.escape(s or "")


def card_keyboard(appid: int, url: str) -> list[list[dict]]:
    return [[{"text": "🛒 Steam", "url": url}, {"text": "ℹ️ " + t("tg_more"), "callback_data": f"i:{appid}"},
             {"text": "⊘ " + t("tg_hide"), "callback_data": f"h:{appid}"}]]


def reason_keyboard(appid: int) -> list[list[dict]]:
    return [[{"text": "😐 " + t("reason_taste"), "callback_data": f"ht:{appid}"},
             {"text": "✓ " + t("reason_owned"), "callback_data": f"ho:{appid}"}],
            [{"text": "↩ " + t("tg_cancel"), "callback_data": f"hx:{appid}"}]]


def hidden_keyboard(appid: int) -> list[list[dict]]:
    return [[{"text": "⊘ " + t("tg_hidden_undo"), "callback_data": f"u:{appid}"}]]


# --------------------------------------------------------------------------- setup helper

def wait_for_start(tg: Telegram, timeout: int = 180, on_tick=None) -> dict | None:
    """After the user presses Start in their bot: return {'chat_id', 'name'} from the first /start message."""
    offset = 0
    for u in tg.poll(0, 0):                      # skip anything older than this setup session
        offset = max(offset, u["update_id"] + 1)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if on_tick:
            on_tick(int(deadline - time.time()))
        for u in tg.poll(offset, 10):
            offset = max(offset, u["update_id"] + 1)
            msg = u.get("message") or {}
            if (msg.get("text") or "").startswith("/start"):
                chat = msg.get("chat", {})
                tg.poll(offset, 0)               # acknowledge
                return {"chat_id": str(chat.get("id")), "name": chat.get("username") or chat.get("first_name", "")}
    return None


# --------------------------------------------------------------------------- updates: buttons & commands

def handle_updates(tg: Telegram, updates: list[dict], answer_command=None) -> int:
    """Apply button presses and commands from *your* chat only. Returns the next offset."""
    offset = 0
    for u in updates:
        offset = max(offset, u["update_id"] + 1)
        cq = u.get("callback_query")
        msg = (cq or {}).get("message") or u.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        if not chat_id or chat_id != tg.chat_id:
            continue                                     # someone else found the bot: ignore
        if cq:
            _callback(tg, cq, msg)
        elif (msg.get("text") or "").startswith("/") and answer_command:
            text = msg["text"].strip()
            cmd, _, arg = text.partition(" ")
            answer_command(cmd.split("@")[0].lstrip("/").lower(), arg.strip())
    return offset


def _callback(tg: Telegram, cq: dict, msg: dict) -> None:
    from ..steam import get_items
    data = cq.get("data", "")
    action, _, raw = data.partition(":")
    if not raw.isdigit():
        tg.answer(cq["id"])
        return
    appid = int(raw)
    chat_id, mid = msg["chat"]["id"], msg.get("message_id")
    if action == "h":
        tg.edit_markup(chat_id, mid, reason_keyboard(appid))
        tg.answer(cq["id"], t("tg_why_hide"))
    elif action in ("ht", "ho"):
        item = get_items([appid], with_price=False).get(appid)
        prefs.hide(appid, item.name if item else f"App {appid}", "taste" if action == "ht" else "owned")
        tg.edit_markup(chat_id, mid, hidden_keyboard(appid))
        tg.answer(cq["id"], t("tg_hidden_ok"))
    elif action == "hx":
        url = f"https://store.steampowered.com/app/{appid}/"
        tg.edit_markup(chat_id, mid, card_keyboard(appid, url))
        tg.answer(cq["id"])
    elif action == "u":
        prefs.unhide(appid)
        tg.edit_markup(chat_id, mid, card_keyboard(appid, f"https://store.steampowered.com/app/{appid}/"))
        tg.answer(cq["id"], t("tg_restored"))
    elif action == "i":
        prefs.log_feedback(appid, "info")
        tg.answer(cq["id"], "…")
        from .runner import info_text
        tg.send_text(info_text(appid))
    else:
        tg.answer(cq["id"])


__all__ = ["Telegram", "TelegramError", "card_keyboard", "handle_updates", "wait_for_start", "sale_name"]
