"""G6: every channel formats and delivers correctly (against recording fake servers)."""
import json
import xml.dom.minidom

import pytest

from helpers import item
from steamsift import prefs
from steamsift.itad import History
from steamsift.notify import channels
from steamsift.notify.cards import Card, discord_embed, telegram_caption
from steamsift.notify.telegram import Telegram, TelegramError, handle_updates, wait_for_start
from steamsift.recommender import Rec


class FakeResp:
    def __init__(self, data=None, status=200, text=""):
        self._data, self.status_code, self.text = data, status, text or json.dumps(data)

    def json(self):
        return self._data


class FakeTelegram:
    """Records Bot API calls; scripted getUpdates."""

    def __init__(self, fail_photo=False, updates=None):
        self.calls, self.fail_photo, self.updates = [], fail_photo, list(updates or [])

    def post(self, url, json=None, timeout=None):
        method = url.rsplit("/", 1)[1]
        self.calls.append((method, json))
        if method == "sendPhoto" and self.fail_photo:
            return FakeResp({"ok": False, "description": "wrong file identifier"})
        if method == "getUpdates":
            off = (json or {}).get("offset", 0)
            return FakeResp({"ok": True, "result": [u for u in self.updates if u["update_id"] >= off]})
        if method == "getMe":
            return FakeResp({"ok": True, "result": {"username": "my_sift_bot"}})
        return FakeResp({"ok": True, "result": {"message_id": 1}})

    def methods(self):
        return [m for m, _ in self.calls]


def card(appid=620, kind="wish_lowest", **kw) -> Card:
    r = Rec(item(appid, "Portal <2> & Friends"), cos=0, quality=0.9, intent=1, why="like Talos · puzzle",
            is_wish=True, hist=History(75), score=88)
    c = Card.from_rec(r, kind)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def test_telegram_card_caption_is_safe_html_and_short():
    cap = telegram_caption(card())
    assert "Portal &lt;2&gt; &amp; Friends" in cap and "<b>" in cap and len(cap) <= 1024
    assert "−50%" in cap and "like Talos" in cap


def test_send_card_with_cover_and_buttons():
    fake = FakeTelegram()
    Telegram("T", "42", session=fake).send_card(card())
    method, payload = fake.calls[0]
    assert method == "sendPhoto" and payload["chat_id"] == "42" and payload["photo"].endswith("header.jpg")
    buttons = payload["reply_markup"]["inline_keyboard"][0]
    assert buttons[0]["url"].endswith("/app/620/")
    assert [b.get("callback_data") for b in buttons[1:]] == ["i:620", "h:620"]


def test_send_card_falls_back_to_text_when_cover_fails():
    fake = FakeTelegram(fail_photo=True)
    Telegram("T", "42", session=fake).send_card(card())
    assert fake.methods() == ["sendPhoto", "sendMessage"]


def test_digest_album_plus_numbered_list_with_hide_buttons():
    fake = FakeTelegram()
    Telegram("T", "42", session=fake).send_digest([card(a) for a in range(1, 13)], "12 deals")
    assert fake.methods() == ["sendMediaGroup", "sendMessage"]
    media = fake.calls[0][1]["media"]
    assert len(media) == 10 and media[0]["caption"]
    rows = fake.calls[1][1]["reply_markup"]["inline_keyboard"]
    assert sum(len(r) for r in rows) == 12 and rows[0][0]["callback_data"] == "h:1"


def _cb(data, chat=42, uid=1):
    return {"update_id": uid, "callback_query": {"id": f"cb{uid}", "data": data,
                                                 "message": {"message_id": 7, "chat": {"id": chat}}}}


def test_hide_flow_from_telegram(monkeypatch):
    from steamsift import steam
    monkeypatch.setattr(steam, "get_items", lambda ids, with_price=True: {i: item(i, f"Game {i}") for i in ids})
    fake = FakeTelegram()
    tg = Telegram("T", "42", session=fake)
    handle_updates(tg, [_cb("h:777")])
    edit = next(p for m, p in fake.calls if m == "editMessageReplyMarkup")
    assert [b["callback_data"] for b in edit["reply_markup"]["inline_keyboard"][0]] == ["ht:777", "ho:777"]
    handle_updates(tg, [_cb("ho:777", uid=2)])
    assert prefs.load_hidden()[777]["reason"] == "owned"
    handle_updates(tg, [_cb("u:777", uid=3)])
    assert 777 not in prefs.load_hidden()


def test_foreign_chats_are_ignored():
    fake = FakeTelegram()
    seen = []
    off = handle_updates(Telegram("T", "42", session=fake), [_cb("h:1", chat=999, uid=5),
                         {"update_id": 6, "message": {"chat": {"id": 999}, "text": "/budget 1"}}],
                         lambda c, a: seen.append(c))
    assert fake.calls == [] and seen == [] and off == 7


def test_commands_are_routed():
    seen = []
    handle_updates(Telegram("T", "42", session=FakeTelegram()),
                   [{"update_id": 1, "message": {"chat": {"id": 42}, "text": "/info@my_sift_bot elden ring"}}],
                   lambda c, a: seen.append((c, a)))
    assert seen == [("info", "elden ring")]


def test_wait_for_start_returns_chat():
    """Old updates are skipped; the first /start sent during setup links the chat."""
    old = {"update_id": 10, "message": {"text": "/start", "chat": {"id": 1, "username": "stranger"}}}
    fake = FakeTelegram(updates=[old])
    tg = Telegram("T", session=fake)

    def user_presses_start(_seconds_left):
        if len(fake.updates) == 1:
            fake.updates.append({"update_id": 11, "message": {"text": "/start", "chat": {"id": 4242,
                                                                                         "username": "me"}}})
    assert wait_for_start(tg, timeout=5, on_tick=user_presses_start) == {"chat_id": "4242", "name": "me"}


def test_telegram_errors_are_raised():
    class Bad(FakeTelegram):
        def post(self, url, json=None, timeout=None):
            return FakeResp({"ok": False, "description": "Unauthorized"}, 401)
    with pytest.raises(TelegramError):
        Telegram("bad", session=Bad()).get_me()


# --------------------------------------------------------------------------- other channels

class Recorder:
    def __init__(self, status=204):
        self.posts, self.status = [], status

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append((url, json, headers or {}))
        return FakeResp({}, self.status, "")


def test_discord_embeds_chunked_by_ten():
    rec = Recorder()
    channels.discord_send("https://discord/hook", [card(a) for a in range(1, 15)], "title", session=rec)
    assert [len(p[1]["embeds"]) for p in rec.posts] == [10, 4] and rec.posts[0][1]["content"] == "**title**"
    emb = discord_embed(card())
    assert emb["image"]["url"].endswith("header.jpg") and emb["url"].endswith("/app/620/")


def test_discord_errors_surface():
    with pytest.raises(channels.ChannelError):
        channels.discord_send("https://x", [card()], session=Recorder(status=404))


def test_ntfy_json_publish_keeps_unicode():
    rec = Recorder(status=200)
    c = card(title="Ведьмак 3")
    channels.ntfy_send("https://ntfy.sh/", "sift-abc", [c], token="tok", session=rec)
    url, body, headers = rec.posts[0]
    assert url == "https://ntfy.sh" and body["topic"] == "sift-abc" and "Ведьмак 3" in body["title"]
    assert body["click"].endswith("/app/620/") and headers["Authorization"] == "Bearer tok"


def test_desktop_toast_on_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(channels.sys, "platform", "win32")
    monkeypatch.setattr(channels, "_download", lambda url: "C:\\tmp\\cover.jpg")
    channels.desktop_send([card()], runner=lambda argv, **kw: calls.append((argv, kw)))
    argv, kw = calls[0]
    assert argv[0] == "powershell" and "ToastNotificationManager" in argv[-1]
    xml_text = open(kw["env"]["SIFT_TOAST_XML"], encoding="utf-8").read()
    doc = xml.dom.minidom.parseString(xml_text)              # well-formed even with <, &, quotes in titles
    assert doc.getElementsByTagName("image")[0].getAttribute("src") == "C:\\tmp\\cover.jpg"


def test_desktop_batches_into_one_summary(monkeypatch):
    calls = []
    monkeypatch.setattr(channels.sys, "platform", "darwin")
    channels.desktop_send([card(a) for a in range(1, 6)], "5 deals", runner=lambda argv, **kw: calls.append(argv))
    assert len(calls) == 1 and calls[0][0] == "osascript"


def test_desktop_linux_notify_send(monkeypatch):
    calls = []
    monkeypatch.setattr(channels.sys, "platform", "linux")
    monkeypatch.setattr(channels.shutil, "which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr(channels, "_download", lambda url: "")
    channels.desktop_send([card()], runner=lambda argv, **kw: calls.append(argv))
    assert calls[0][0] == "notify-send"


def test_email_html_and_text(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"] = (host, port)

        def starttls(self):
            sent["tls"] = True

        def login(self, user, pw):
            sent["login"] = (user, pw)

        def send_message(self, msg):
            sent["msg"] = msg

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(channels.smtplib, "SMTP", FakeSMTP)
    channels.email_send("smtp.example", 587, "me@example", "pw", "me@example", [card()], "sift digest")
    msg = sent["msg"]
    assert sent["tls"] and sent["login"] == ("me@example", "pw") and msg["Subject"] == "sift digest"
    html_part = msg.get_body(("html",)).get_content()
    assert "Portal &lt;2&gt;" in html_part and "header.jpg" in html_part


def test_desktop_toast_failure_is_reported(monkeypatch):
    class Res:
        returncode, stderr = 1, b"Access denied"
    monkeypatch.setattr(channels.sys, "platform", "win32")
    monkeypatch.setattr(channels, "_download", lambda url: "")
    with pytest.raises(channels.ChannelError, match="Access denied"):
        channels.desktop_send([card()], runner=lambda argv, **kw: Res())
