"""Delivery channels besides Telegram: Discord webhook, ntfy push, desktop toast, email."""
from __future__ import annotations

import os
import shutil
import smtplib
import subprocess
import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path

import requests

from ..i18n import t
from ..net import SESSION
from .cards import Card, discord_embed, email_html


class ChannelError(RuntimeError):
    pass


def _check(r: requests.Response, what: str) -> None:
    if r.status_code >= 300:
        raise ChannelError(f"{what}: HTTP {r.status_code} {r.text[:120]}")


# --------------------------------------------------------------------------- Discord

def discord_send(webhook: str, cards: list[Card], title: str = "", session=SESSION) -> None:
    for i in range(0, len(cards), 10):                       # Discord: max 10 embeds per message
        payload = {"username": "sift", "embeds": [discord_embed(c) for c in cards[i: i + 10]]}
        if title and i == 0:
            payload["content"] = f"**{title}**"
        try:
            r = session.post(webhook, json=payload, timeout=15)
        except requests.RequestException as e:
            raise ChannelError(f"discord: {type(e).__name__}") from None
        _check(r, "discord")


# --------------------------------------------------------------------------- ntfy

def ntfy_send(server: str, topic: str, cards: list[Card], token: str = "", session=SESSION) -> None:
    """JSON publishing keeps non-ASCII titles intact (headers would need RFC 2047)."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    for c in cards:
        body = {"topic": topic, "title": f"{c.icon} {c.title}"[:250], "message": c.plain(), "click": c.url,
                "attach": c.image, "tags": ["video_game"],
                "priority": 4 if c.kind in ("wish_target", "wish_lowest", "ending") else 3,
                "actions": [{"action": "view", "label": "Steam", "url": c.url}]}
        try:
            r = session.post(server.rstrip("/"), json=body, headers=headers, timeout=15)
        except requests.RequestException as e:
            raise ChannelError(f"ntfy: {type(e).__name__}") from None
        _check(r, "ntfy")


# --------------------------------------------------------------------------- email

def email_send(host: str, port: int, user: str, password: str, to: str, cards: list[Card], title: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = user or to
    msg["To"] = to
    msg.set_content("\n\n".join(c.plain() + f"\n{c.url}" for c in cards))
    msg.add_alternative(email_html(cards, title), subtype="html")
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls()
        with server:
            if user:
                server.login(user, password)
            server.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        raise ChannelError(f"email: {e}") from None


# --------------------------------------------------------------------------- desktop

_PS_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml([System.IO.File]::ReadAllText($env:SIFT_TOAST_XML, [System.Text.Encoding]::UTF8))
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show(
    [Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def _xml(s: str) -> str:
    from xml.sax.saxutils import escape
    return escape(s or "", {'"': "&quot;"})


def toast_xml(card: Card, image_path: str = "") -> str:
    img = f'<image placement="hero" src="{_xml(image_path)}"/>' if image_path else ""
    body = f"{card.price_line()}" + (f" · {card.verdict}" if card.verdict else "")
    return (f'<toast activationType="protocol" launch="{_xml(card.url)}"><visual><binding template="ToastGeneric">'
            f"<text>{_xml(card.headline)}</text><text>{_xml(card.title)}</text><text>{_xml(body)}</text>{img}"
            f'</binding></visual><actions><action content="Steam" activationType="protocol" '
            f'arguments="{_xml(card.url)}"/></actions></toast>')


def _download(url: str) -> str:
    try:
        r = SESSION.get(url, timeout=10)
        if r.status_code == 200:
            path = Path(tempfile.gettempdir()) / f"sift-cover-{abs(hash(url))}.jpg"
            path.write_bytes(r.content)
            return str(path)
    except requests.RequestException:
        pass
    return ""


def desktop_send(cards: list[Card], title: str = "", runner=subprocess.run) -> None:
    if not cards:
        return
    if len(cards) > 3:   # don't flood: one summary toast for big batches
        summary = Card(0, "top", title or t("ev_top"), "", "", 0, "", 0, None, 0,
                       " · ".join(c.title for c in cards[:5]), 0, cards[0].url, cards[0].image)
        cards = [summary]
    for c in cards:
        if sys.platform == "win32":
            path = Path(tempfile.gettempdir()) / "sift-toast.xml"
            path.write_text(toast_xml(c, _download(c.image) if c.image else ""), encoding="utf-8")
            res = runner(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command",
                          _PS_TOAST], env={**os.environ, "SIFT_TOAST_XML": str(path)}, capture_output=True,
                         timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if getattr(res, "returncode", 0):
                err = (getattr(res, "stderr", b"") or b"")
                err = err.decode(errors="replace") if isinstance(err, bytes) else str(err)
                raise ChannelError(f"desktop: Windows refused the toast ({err.strip()[:160]})")
        elif sys.platform == "darwin":
            script = f'display notification {_as(c.price_line() + " " + c.verdict)} with title {_as(c.title)} ' \
                     f'subtitle {_as(c.headline)}'
            runner(["osascript", "-e", script], capture_output=True, timeout=15)
        elif shutil.which("notify-send"):
            icon = _download(c.image) if c.image else ""
            runner(["notify-send", "-a", "sift", *(["-i", icon] if icon else []), c.title,
                    f"{c.headline}\n{c.price_line()} {c.verdict}"], capture_output=True, timeout=15)
        else:
            raise ChannelError("desktop: no notifier found (install libnotify / notify-send)")


def _as(s: str) -> str:
    return '"' + (s or "").replace("\\", "\\\\").replace('"', '\\"') + '"'
