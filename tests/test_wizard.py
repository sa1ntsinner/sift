"""G1: the first-run wizard walks every step with live validation and writes config + keys."""
import asyncio

from steamsift import config
from steamsift.config import Settings
from steamsift.tui.wizard import Wizard

KEY = "A" * 32
SID = "76561198012345678"


class FakeServices:
    def __init__(self, games=145, playtime=True):
        self.opened, self.secrets, self.games, self.playtime = [], {}, games, playtime
        self.clip = ""

    def clipboard(self):
        return self.clip

    def scan(self):
        from steamsift.autodetect import Account, Found
        return Found("C:/Steam", [Account(SID, "sa1ntsinner", True)],
                     {"name": "Alex's Family", "member_steam_ids": [SID, "76561198000000001"]})

    def check_steam_key(self, key):
        return key == KEY

    def check_itad_key(self, key):
        return True

    def resolve_profile(self, text, key):
        return SID if "sa1nt" in text and key == KEY else None

    def summary(self, sid):
        return {"name": "sa1ntsinner", "visibility": 3}

    def library(self, sid):
        return self.games, self.playtime

    def wishlist(self, sid):
        return 196

    def detect_ip(self):
        return "TR"

    def family(self, sid):
        return {"name": "Alex's Family", "member_steam_ids": [SID, "76561198000000001"]}

    def names(self, ids):
        return {i: "sam" for i in ids}

    def search_games(self, q):
        return [(620, "Portal 2"), (400, "Portal")]

    def telegram_me(self, token):
        return "my_sift_bot" if token.startswith("123:") else None

    def telegram_wait(self, token):
        return {"chat_id": "4242", "name": "me"}

    def send_test(self, channel):
        return []

    def open_url(self, url):
        self.opened.append(url)

    def save_secret(self, name, value):
        self.secrets[name] = value


async def wait_for(pilot, cond, what):
    for _ in range(150):
        await pilot.pause(0.02)
        if cond():
            return
    raise AssertionError(f"timed out waiting for {what}")


def step(app):
    return app._visible_steps()[app.step]


async def next_step(pilot, app, expected):
    nxt = app.query_one("#next")
    # Textual ignores clicks on a Button during its 200 ms "-active" press effect; humans never hit that.
    await wait_for(pilot, lambda: not nxt.disabled and not nxt.has_class("-active"), f"Next ready on {step(app)}")
    await pilot.click("#next")
    await wait_for(pilot, lambda: step(app) == expected, expected)


def test_full_wizard_with_telegram(monkeypatch):
    svc = FakeServices()
    config.cfg.settings = Settings()                       # fresh settings for this test
    config.cfg.profile = config.cfg.settings.profiles["main"]
    config.cfg.steam_api_key = config.cfg.steam_id = config.cfg.country = ""

    async def go():
        app = Wizard(svc)
        async with app.run_test(size=(110, 40)) as pilot:
            assert step(app) == "welcome" and app.query_one("#back").disabled
            await pilot.click("#lang-ru")
            await next_step(pilot, app, "key")
            assert app.query_one("#next").disabled, "can't continue without a key"
            await pilot.click("#open-key")
            app.query_one("#steam-key").value = "B" * 32         # wrong key
            await wait_for(pilot, lambda: "✗" in str(app.query_one("#key-status").render()), "rejection")
            assert app.query_one("#next").disabled
            app.query_one("#steam-key").value = KEY
            await next_step(pilot, app, "itad")
            await next_step(pilot, app, "profile")
            app.query_one("#steam-profile").value = "https://steamcommunity.com/id/sa1ntsinner/"
            await wait_for(pilot, lambda: "sa1ntsinner" in str(app.query_one("#profile-status").render()), "profile")
            await next_step(pilot, app, "privacy")
            await wait_for(pilot, lambda: "196" in str(app.query_one("#privacy-list").render()), "privacy list")
            await next_step(pilot, app, "region")
            await wait_for(pilot, lambda: app.a.country == "TR", "IP suggestion pre-selects TR")
            await pilot.click("#region-search")
            await pilot.press(*"казах")
            await wait_for(pilot, lambda: app.query_one("#region-options").option_count == 1, "search results")
            await pilot.press("enter")                       # Enter in the search box takes the best match
            await wait_for(pilot, lambda: app.a.country == "KZ", "user picks Kazakhstan")
            await next_step(pilot, app, "family")
            await wait_for(pilot, lambda: "Alex" in str(app.query_one("#family-found").render()), "family")
            await next_step(pilot, app, "prefs")
            await pilot.click("#pref-third")                     # hide 3rd-party-account games
            app.query_one("#pref-budget").value = "1500"
            await next_step(pilot, app, "notify")                 # seeds skipped: 145 games with playtime
            await pilot.click("#ch-telegram")
            await pilot.pause()
            assert app.query_one("#next").disabled, "Telegram must be linked first"
            app.query_one("#tg-token").value = "123:ABC"
            await pilot.click("#tg-link")
            await wait_for(pilot, lambda: app.a.telegram_chat == "4242", "telegram linked")
            await next_step(pilot, app, "done")
            await pilot.click("#show")
        return app.return_value

    result = asyncio.run(go())
    assert result == "show"
    p = config.cfg.profile
    assert (p.steam_id, p.country, p.budget) == (SID, "KZ", 1500.0)
    assert p.filters.third_party is False and "telegram" in p.notify.channels and p.notify.telegram_chat == "4242"
    assert config.cfg.settings.lang == "ru"
    assert svc.secrets == {"steam_api_key": KEY, "telegram_token": "123:ABC"}
    assert "https://steamcommunity.com/dev/apikey" in svc.opened and "https://t.me/my_sift_bot" in svc.opened
    reloaded = Settings.load()
    assert reloaded.profiles["main"].country == "KZ" and reloaded.profiles["main"].notify.telegram_chat == "4242"


def test_cold_start_shows_favourites_step():
    svc = FakeServices(games=2, playtime=True)
    config.cfg.settings = Settings()
    config.cfg.profile = config.cfg.settings.profiles["main"]

    async def go():
        app = Wizard(svc)
        app.a.steam_key, app.a.steam_id, app.a.country = KEY, SID, "TR"
        app.valid |= {"key", "profile", "region"}
        async with app.run_test(size=(110, 40)) as pilot:
            app.a.games = 2
            app.step = app._visible_steps().index("prefs")
            app._render_step()
            await next_step(pilot, app, "seeds")
            app.query_one("#seed-search").value = "portal"
            await pilot.click("#seed-search")
            await pilot.press("enter")
            await wait_for(pilot, lambda: app.query_one("#seed-options").option_count == 2, "search results")
            await pilot.press("enter")                       # results get focus with the first one highlighted
            await wait_for(pilot, lambda: app.a.seeds == [620], "seed picked")
            await next_step(pilot, app, "notify")
            await next_step(pilot, app, "done")
            await pilot.click("#exit")
        return app.return_value

    assert asyncio.run(go()) == "exit"
    assert config.cfg.profile.seeds == [620]


def test_scan_fills_the_account_and_keys_come_from_the_clipboard():
    svc = FakeServices()
    config.cfg.settings = Settings()
    config.cfg.profile = config.cfg.settings.profiles["main"]
    config.cfg.steam_api_key = config.cfg.steam_id = config.cfg.country = config.cfg.itad_api_key = ""

    async def go():
        app = Wizard(svc)
        async with app.run_test(size=(110, 44)) as pilot:
            await pilot.click("#scan")
            await wait_for(pilot, lambda: "sa1ntsinner" in str(app.query_one("#scan-result").render()), "scan")
            assert app.a.steam_id == SID and "Alex" in str(app.query_one("#scan-result").render())
            await next_step(pilot, app, "key")
            svc.clip = "some text " + KEY + " copied from the browser"
            await wait_for(pilot, lambda: app.query_one("#steam-key").value == KEY, "key from the clipboard")
            await next_step(pilot, app, "itad")
            svc.clip = "a" * 40
            await wait_for(pilot, lambda: app.query_one("#itad-key").value == "a" * 40, "ITAD key from the clipboard")
            await next_step(pilot, app, "privacy")          # profile skipped: the scan found the account
            await wait_for(pilot, lambda: "196" in str(app.query_one("#privacy-list").render()), "privacy")
        return True

    assert asyncio.run(go())
    assert svc.secrets["steam_api_key"] == KEY and svc.secrets["itad_api_key"] == "a" * 40


def test_key_patterns_and_accounts_file(tmp_path, monkeypatch):
    from steamsift import autodetect
    assert autodetect.key_in("x " + "A1" * 16 + " y", "steam") == "A1" * 16
    assert autodetect.key_in("a1" * 16, "steam") == ""                       # Steam keys are upper case
    assert autodetect.key_in("0f" * 20, "itad") == "0f" * 20
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "loginusers.vdf").write_text(
        '"users" { "76561190000000001" { "PersonaName" "old" "Timestamp" "100" }'
        ' "76561190000000002" { "PersonaName" "main" "MostRecent" "1" "Timestamp" "50" } }', encoding="utf-8")
    monkeypatch.setattr(autodetect, "steam_roots", lambda: [tmp_path])
    assert [a.persona for a in autodetect.accounts()] == ["main", "old"]
