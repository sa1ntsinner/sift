"""First-run setup wizard (Textual). Every step validates live; network calls run in worker threads.

Network/OS actions go through `Services`, so the whole flow can be driven headless in tests.
"""
from __future__ import annotations

import webbrowser
from dataclasses import dataclass, field

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.widgets import (Button, ContentSwitcher, Input, Label, OptionList, RadioButton, RadioSet, Select, Static,
                             Switch)
from textual.widgets.option_list import Option

from .. import config, region, steamid
from ..i18n import t
from .theme import BASE_CSS, THEMES

KEY_URL = "https://steamcommunity.com/dev/apikey"
PRIVACY_URL = "https://steamcommunity.com/my/edit/settings"
ITAD_URL = "https://isthereanydeal.com/apps/my/"
BOTFATHER_URL = "https://t.me/BotFather"


# --------------------------------------------------------------------------- services (real network by default)

class Services:
    def check_steam_key(self, key: str) -> bool | None:
        from ..doctor import check_steam_key
        return check_steam_key(key)

    def check_itad_key(self, key: str) -> bool | None:
        from ..doctor import check_itad_key
        return check_itad_key(key)

    def resolve_profile(self, text: str, key: str) -> str | None:
        return steamid.resolve(text, key)

    def summary(self, sid: str) -> dict:
        from ..steam import get_player_summaries
        return get_player_summaries([sid]).get(sid, {})

    def library(self, sid: str) -> tuple[int, bool]:
        from ..steam import get_owned_games
        games = get_owned_games(sid)
        return len(games), any(g.get("playtime_forever") for g in games.values())

    def wishlist(self, sid: str) -> int | None:
        from ..doctor import wishlist_count
        return wishlist_count(sid)

    def detect_ip(self) -> str | None:
        return region.detect_ip_country()

    def family(self, sid: str) -> dict:
        from ..localsteam import family_from_client
        return family_from_client(sid)

    def names(self, ids: list[str]) -> dict[str, str]:
        from ..steam import get_player_summaries
        return {k: v.get("name", "") for k, v in get_player_summaries(ids).items()}

    def search_games(self, q: str) -> list[tuple[int, str]]:
        from ..steam import store_lookup
        return store_lookup(q)[:8]

    def telegram_me(self, token: str) -> str | None:
        from ..notify.telegram import Telegram, TelegramError
        try:
            return Telegram(token).get_me()["username"]
        except TelegramError:
            return None

    def telegram_wait(self, token: str) -> dict | None:
        from ..notify.telegram import Telegram, wait_for_start
        return wait_for_start(Telegram(token), timeout=240)

    def send_test(self, channel: str) -> list[str]:
        from ..notify.runner import send_test
        return send_test([channel])[1]

    def open_url(self, url: str) -> None:
        webbrowser.open(url)

    def save_secret(self, name: str, value: str) -> None:
        config.set_secret(name, value)

    def scan(self):
        from ..autodetect import scan
        return scan()

    def clipboard(self) -> str:
        from ..autodetect import clipboard_text
        return clipboard_text()


@dataclass
class Answers:
    lang: str = ""
    steam_key: str = ""
    steam_id: str = ""
    user: str = ""
    games: int = 0
    playtime: bool = True
    country: str = ""
    family: list[str] = field(default_factory=list)
    family_auto: bool = True
    itad_key: str = ""
    seeds: list[int] = field(default_factory=list)
    channel: str = ""
    telegram_token: str = ""
    telegram_chat: str = ""


STEPS = ["welcome", "key", "itad", "profile", "privacy", "region", "family", "prefs", "seeds", "notify", "done"]
STEP_TITLE = {"welcome": "wz_s_welcome", "key": "wz_s_key", "itad": "wz_s_itad", "profile": "wz_s_profile",
              "privacy": "wz_s_privacy", "region": "wz_s_region", "family": "wz_s_family", "prefs": "wz_s_prefs",
              "seeds": "wz_s_seeds", "notify": "wz_s_notify", "done": "wz_s_done"}


class Wizard(App):
    TITLE = "sift setup"
    CSS = BASE_CSS + """
    #frame { width: 92; max-width: 100%; height: auto; max-height: 100%; padding: 1 3;
             border: round $panel; background: $surface; }
    #dots { height: 1; margin-bottom: 1; }
    .step { height: auto; }
    .step Static { margin-bottom: 1; }
    .row { height: auto; margin-bottom: 1; }
    .row Button { margin-right: 2; }
    #nav { height: 3; margin-top: 1; }
    #nav #back { margin-right: 2; }
    #nav Static { width: 1fr; }
    .status { height: auto; min-height: 1; }
    OptionList { height: auto; max-height: 8; }
    Select { width: 40; }
    .pref { height: 3; }
    .pref Label { width: 34; padding-top: 1; }
    .logo { color: $primary; text-style: bold; }
    .steps-list { margin-bottom: 1; }
    .link { color: $secondary; }
    #scan-result { margin-top: 1; }
    #lang { layout: horizontal; height: auto; border: none; background: transparent; padding: 0; margin-bottom: 1; }
    #lang RadioButton { width: auto; margin-right: 4; background: transparent; }
    """
    BINDINGS = [("ctrl+q", "quit_wizard", "Quit"), ("escape", "back", "Back")]

    def __init__(self, services: Services | None = None):
        super().__init__()
        self.svc = services or Services()
        self.a = Answers(lang=config.cfg.lang, country=config.cfg.country, steam_id=config.cfg.steam_id,
                         steam_key=config.cfg.steam_api_key, itad_key=config.cfg.itad_api_key)
        self.step = 0
        self.valid: set[str] = {"welcome", "privacy", "family", "itad", "prefs", "seeds", "notify", "done"}
        self.result = "exit"
        self.scanned = False
        self._clip_seen = ""

    # ---------------------------------------------------------------- layout

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="frame"):
                yield Static(id="dots")
                with ContentSwitcher(initial="welcome", id="steps"):
                    yield from self._welcome()
                    yield from self._key()
                    yield from self._profile()
                    yield from self._privacy()
                    yield from self._region()
                    yield from self._family()
                    yield from self._itad()
                    yield from self._prefs()
                    yield from self._seeds()
                    yield from self._notify()
                    yield from self._done()
                with Horizontal(id="nav"):
                    yield Button(t("wz_back"), id="back")
                    yield Static()
                    yield Button(t("wz_next"), id="next", variant="primary")

    def _welcome(self):
        with Vertical(id="welcome", classes="step"):
            yield Static("sift", classes="logo")
            yield Static(t("wz_welcome"))
            yield Static(t("wz_need"), classes="steps-list")
            with RadioSet(id="lang"):
                yield RadioButton("English", value=self.a.lang != "ru", id="lang-en")
                yield RadioButton("Русский", value=self.a.lang == "ru", id="lang-ru")
            yield Static(t("wz_scan_ask"))
            with Horizontal(classes="row"):
                yield Button(t("wz_scan_yes"), id="scan", variant="primary")
                yield Button(t("wz_scan_no"), id="manual")
            yield Static(id="scan-result", classes="status")

    def _key(self):
        with Vertical(id="key", classes="step"):
            yield Static(t("wz_key_title"), classes="title")
            yield Static(t("wz_key_steps", url=KEY_URL))
            with Horizontal(classes="row"):
                yield Button(t("wz_open_key_page"), id="open-key")
            yield Static(t("wz_clip_watch"), classes="muted")
            yield Input(value=self.a.steam_key, placeholder="XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX", password=True,
                        id="steam-key")
            yield Static(classes="status", id="key-status")

    def _profile(self):
        with Vertical(id="profile", classes="step"):
            yield Static(t("wz_profile_title"), classes="title")
            yield Static(t("wz_profile_help"))
            yield Input(value=self.a.steam_id, placeholder="https://steamcommunity.com/id/…", id="steam-profile")
            yield Static(classes="status", id="profile-status")

    def _privacy(self):
        with Vertical(id="privacy", classes="step"):
            yield Static(t("wz_privacy_title"), classes="title")
            yield Static(id="privacy-list", classes="status")
            with Horizontal(classes="row"):
                yield Button(t("wz_open_privacy"), id="open-privacy")
                yield Button(t("wz_recheck"), id="recheck")

    def _region(self):
        with Vertical(id="region", classes="step"):
            yield Static(t("wz_region_title"), classes="title")
            yield Static(t("wz_region_help"))
            yield Static(id="region-hint", classes="status")
            yield Input(placeholder=t("wz_region_search"), id="region-search")
            yield OptionList(id="region-options")
            yield Static(id="region-status", classes="status")

    def _family(self):
        with Vertical(id="family", classes="step"):
            yield Static(t("wz_family_title"), classes="title")
            yield Static(id="family-found", classes="status")
            yield Static(t("wz_family_manual"), classes="muted")
            yield Input(placeholder="https://steamcommunity.com/id/… https://steamcommunity.com/profiles/…",
                        id="family-links")

    def _itad(self):
        with Vertical(id="itad", classes="step"):
            yield Static(t("wz_itad_title"), classes="title")
            yield Static(t("wz_itad_steps", url=ITAD_URL))
            with Horizontal(classes="row"):
                yield Button(t("wz_open_itad"), id="open-itad")
            yield Static(t("wz_clip_watch"), classes="muted")
            yield Input(value=self.a.itad_key, placeholder=t("wz_optional"), password=True, id="itad-key")
            yield Static(classes="status", id="itad-status")

    def _prefs(self):
        f = config.cfg.profile.filters
        with VerticalScroll(id="prefs", classes="step"):
            yield Static(t("wz_prefs_title"), classes="title")
            with Horizontal(classes="pref"):
                yield Label(t("wz_pref_game_lang"))
                yield Select([(t("wz_any"), ""), (t("wz_subs"), "subs"), (t("wz_audio"), "audio")],
                             value=f.game_lang, allow_blank=False, id="pref-game-lang")
            with Horizontal(classes="pref"):
                yield Label("Steam Deck")
                yield Select([(t("wz_any"), "any"), ("Playable", "playable"), ("Verified", "verified")],
                             value=f.deck, allow_blank=False, id="pref-deck")
            with Horizontal(classes="pref"):
                yield Label(t("wz_pref_adult"))
                yield Switch(value=not f.adult, id="pref-adult")
            with Horizontal(classes="pref"):
                yield Label(t("wz_pref_ea"))
                yield Switch(value=f.early_access == "hide", id="pref-ea")
            with Horizontal(classes="pref"):
                yield Label(t("wz_pref_third"))
                yield Switch(value=not f.third_party, id="pref-third")
            with Horizontal(classes="pref"):
                yield Label(t("wz_pref_budget"))
                yield Input(value="" if config.cfg.budget is None else f"{config.cfg.budget:g}",
                            placeholder=t("wz_optional"), id="pref-budget")
            with Horizontal(classes="pref"):
                yield Label(t("wz_pref_min_discount"))
                yield Input(value=str(config.cfg.min_discount), id="pref-min-discount", type="integer")

    def _seeds(self):
        with Vertical(id="seeds", classes="step"):
            yield Static(t("wz_seeds_title"), classes="title")
            yield Static(t("wz_seeds_help"))
            yield Input(placeholder=t("wz_seeds_search"), id="seed-search")
            yield OptionList(id="seed-options")
            yield Static(id="seed-chosen", classes="status")

    def _notify(self):
        with Vertical(id="notify", classes="step"):
            yield Static(t("wz_notify_title"), classes="title")
            yield Static(t("wz_notify_help"))
            with RadioSet(id="channel"):
                yield RadioButton("Telegram", id="ch-telegram")
                yield RadioButton(t("wz_ch_desktop"), id="ch-desktop")
                yield RadioButton("ntfy", id="ch-ntfy")
                yield RadioButton(t("wz_ch_later"), value=True, id="ch-later")
            with Vertical(id="tg-box", classes="step"):
                yield Static(t("wz_tg_step1"))
                with Horizontal(classes="row"):
                    yield Button(t("wz_open_botfather"), id="open-botfather")
                yield Input(placeholder="123456789:AA…", password=True, id="tg-token")
                with Horizontal(classes="row"):
                    yield Button(t("wz_tg_link"), id="tg-link", variant="primary")
                yield Static(classes="status", id="tg-status")

    def _done(self):
        with Vertical(id="done", classes="step"):
            yield Static("◆ " + t("wz_done_title"), classes="logo")
            yield Static(id="done-summary")
            with Horizontal(classes="row"):
                yield Button(t("wz_show"), id="show", variant="success")
                yield Button(t("wz_exit"), id="exit")

    # ---------------------------------------------------------------- navigation

    def on_mount(self) -> None:
        for th in THEMES:
            self.register_theme(th)
        self.theme = "sift"
        self.query_one("#tg-box").display = False
        self._render_step()
        self.set_interval(1.0, self._watch_clipboard)

    # ---------------------------------------------------------------- this PC

    @on(Button.Pressed, "#scan")
    def scan_pc(self) -> None:
        self.query_one("#scan-result", Static).update(f"[dim]{t('wz_scan_running')}[/]")
        self.run_scan()

    @on(Button.Pressed, "#manual")
    def manual(self) -> None:
        self.scanned = False
        self.action_next()

    @work(thread=True, exclusive=True, group="scan")
    def run_scan(self) -> None:
        found = self.svc.scan()
        info = self.svc.summary(found.account.steam_id) if found.account and self.a.steam_key else {}
        self.call_from_thread(self._scan_result, found, info)

    def _scan_result(self, found, info) -> None:
        self.scanned = True
        rows = []
        mark = lambda ok: "[$success]✓[/]" if ok else "[$warning]·[/]"  # noqa: E731
        rows.append(f"{mark(bool(found.steam_root))} " + (t("wz_found_steam", path=found.steam_root)
                                                          if found.steam_root else t("wz_found_no_steam")))
        acc = found.account
        if acc:
            self.a.steam_id = acc.steam_id
            self.a.user = info.get("name") or acc.persona
            config.cfg.steam_id = acc.steam_id
            self._mark("profile", True)
            others = len(found.accounts) - 1
            more = "  " + t("wz_found_more", n=others) if others else ""
            rows.append(f"{mark(True)} {t('wz_found_account', name=self.a.user, sid=acc.steam_id)}{more}")
        else:
            rows.append(f"{mark(False)} {t('wz_found_no_account')}")
        if found.family:
            n = len([x for x in found.family.get("member_steam_ids", []) if x != self.a.steam_id])
            rows.append(f"{mark(True)} {t('wz_found_family', name=found.family.get('name'), n=n)}")
        else:
            rows.append(f"{mark(False)} {t('wz_found_no_family')}")
        rows.append(f"{mark(bool(self.a.steam_key))} " + (t("wz_found_key") if self.a.steam_key else t("wz_found_no_key")))
        if self.a.itad_key:
            rows.append(f"{mark(True)} {t('wz_found_itad')}")
        rows.append("\n" + t("wz_scan_next"))
        self.query_one("#scan-result", Static).update("\n".join(rows))
        self.query_one("#next", Button).focus()

    def _watch_clipboard(self) -> None:
        """On a key step with an empty box, a key copied in the browser fills itself in."""
        from ..autodetect import key_in
        name = self._visible_steps()[self.step]
        box_id, kind = {"key": ("#steam-key", "steam"), "itad": ("#itad-key", "itad")}.get(name, ("", ""))
        if not box_id:
            return
        box = self.query_one(box_id, Input)
        if box.value.strip():
            return
        text = self.svc.clipboard()
        key = key_in(text, kind)
        if key and key != self._clip_seen:
            self._clip_seen = key
            box.value = key
            self.notify(t("wz_clip_got"), timeout=3)

    def _visible_steps(self) -> list[str]:
        steps = list(STEPS)
        if self.scanned and self.a.steam_id and "profile" in self.valid:
            steps.remove("profile")      # the scan found the account; privacy shows who it is
        if self.a.games >= 5 and self.a.playtime:
            steps.remove("seeds")        # enough play history: no need for a cold-start quiz
        return steps

    def _render_step(self) -> None:
        steps = self._visible_steps()
        self.step = max(0, min(self.step, len(steps) - 1))
        name = steps[self.step]
        self.query_one("#steps", ContentSwitcher).current = name
        dots = " ".join("●" if i <= self.step else "○" for i in range(len(steps)))
        self.query_one("#dots", Static).update(
            f"[b $primary]{dots}[/]   [b]{t(STEP_TITLE[name])}[/]  [dim]{self.step + 1}/{len(steps)}[/]")
        self.query_one("#back", Button).disabled = self.step == 0
        nxt = self.query_one("#next", Button)
        nxt.display = name != "done"
        nxt.disabled = name not in self.valid
        self._enter(name)

    def _enter(self, name: str) -> None:
        if name == "privacy" and self.a.steam_id:
            self.check_privacy()
        elif name == "region":
            self.suggest_region()
        elif name == "family" and self.a.steam_id:
            self.find_family()
        elif name == "done":
            self._summary()
        focus = {"key": "#steam-key", "profile": "#steam-profile", "region": "#region-search",
                 "itad": "#itad-key", "seeds": "#seed-search"}.get(name)
        if focus:
            self.query_one(focus).focus()

    def _mark(self, step: str, ok: bool) -> None:
        (self.valid.add if ok else self.valid.discard)(step)
        if self._visible_steps()[self.step] == step:
            self.query_one("#next", Button).disabled = not ok

    @on(Button.Pressed, "#next")
    def action_next(self) -> None:
        name = self._visible_steps()[self.step]
        if name not in self.valid:
            return
        if name == "prefs":
            self._read_prefs()
        self.step += 1
        self._render_step()

    @on(Button.Pressed, "#back")
    def action_back(self) -> None:
        if self.step:
            self.step -= 1
            self._render_step()

    def action_quit_wizard(self) -> None:
        self.exit("exit")

    # ---------------------------------------------------------------- step logic

    @on(RadioSet.Changed, "#lang")
    def lang_changed(self, event: RadioSet.Changed) -> None:
        self.a.lang = "ru" if event.pressed.id == "lang-ru" else "en"
        config.cfg.lang = self.a.lang

    @on(Button.Pressed, "#open-key")
    def open_key(self) -> None:
        self.svc.open_url(KEY_URL)

    @on(Input.Changed, "#steam-key")
    def key_changed(self, event: Input.Changed) -> None:
        key = event.value.strip()
        self._mark("key", False)
        if len(key) == 32:
            self.query_one("#key-status", Static).update(f"[dim]{t('wz_checking')}[/]")
            self.validate_key(key)
        elif key:
            self.query_one("#key-status", Static).update(f"[$warning]{t('wz_key_len', n=len(key))}[/]")

    @work(thread=True, exclusive=True, group="key")
    def validate_key(self, key: str) -> None:
        ok = self.svc.check_steam_key(key)
        self.call_from_thread(self._key_result, key, ok)

    def _key_result(self, key: str, ok: bool | None) -> None:
        status = self.query_one("#key-status", Static)
        if ok:
            self.a.steam_key = key
            config.cfg.steam_api_key = key
            self.svc.save_secret("steam_api_key", key)
            status.update(f"[$success]✓ {t('wz_key_ok')}[/]")
            self._mark("key", True)
        elif ok is None:
            status.update(f"[$warning]! {t('dr_network')}[/]")
        else:
            status.update(f"[$error]✗ {t('cfg_key_invalid')}[/]")

    @on(Input.Submitted, "#steam-profile")
    @on(Input.Changed, "#steam-profile")
    def profile_changed(self, event) -> None:
        text = event.value.strip()
        self._mark("profile", False)
        if steamid.parse(text):
            self.query_one("#profile-status", Static).update(f"[dim]{t('wz_checking')}[/]")
            self.resolve_profile(text)

    @work(thread=True, exclusive=True, group="profile")
    def resolve_profile(self, text: str) -> None:
        sid = self.svc.resolve_profile(text, self.a.steam_key)
        info = self.svc.summary(sid) if sid else {}
        games, playtime = self.svc.library(sid) if sid and info else (0, True)
        wl = self.svc.wishlist(sid) if sid else None
        self.call_from_thread(self._profile_result, sid, info, games, playtime, wl)

    def _profile_result(self, sid, info, games, playtime, wl) -> None:
        status = self.query_one("#profile-status", Static)
        if not sid or not info:
            status.update(f"[$error]✗ {t('err_bad_profile', q=self.query_one('#steam-profile', Input).value)}[/]")
            return
        self.a.steam_id, self.a.user, self.a.games, self.a.playtime = sid, info.get("name", ""), games, playtime
        config.cfg.steam_id = sid
        bits = [t("wz_games_n", n=games) if games else t("wz_games_hidden")]
        if wl is not None:
            bits.append(t("wz_wishlist_n", n=wl))
        status.update(f"[$success]✓ {t('wz_is_you', name=info.get('name', '?'))}[/]  [dim]{' · '.join(bits)}[/]")
        self._mark("profile", True)

    @on(Button.Pressed, "#open-privacy")
    def open_privacy(self) -> None:
        self.svc.open_url(PRIVACY_URL)

    @on(Button.Pressed, "#recheck")
    def recheck(self) -> None:
        self.check_privacy()

    @work(thread=True, exclusive=True, group="privacy")
    def check_privacy(self) -> None:
        info = self.svc.summary(self.a.steam_id)
        games, playtime = self.svc.library(self.a.steam_id)
        wl = self.svc.wishlist(self.a.steam_id)
        self.call_from_thread(self._privacy_result, info, games, playtime, wl)

    def _privacy_result(self, info, games, playtime, wl) -> None:
        self.a.games, self.a.playtime = games, playtime

        def line(ok, text, fix=""):
            mark = "[$success]✓[/]" if ok else "[$warning]![/]"
            return f"{mark} {text}" + (f"  [dim]{fix}[/]" if not ok and fix else "")
        rows = [line(info.get("visibility") == 3, t("wz_pv_profile"), t("wz_pv_fix_profile")),
                line(games > 0, t("wz_pv_games", n=games), t("wz_pv_fix_games")),
                line(playtime or games == 0, t("wz_pv_playtime"), t("wz_pv_fix_playtime")),
                line(bool(wl), t("wz_pv_wishlist", n=wl or 0), t("wz_pv_fix_wishlist"))]
        self.query_one("#privacy-list", Static).update("\n".join(rows))

    @work(thread=True, exclusive=True, group="region")
    def suggest_region(self) -> None:
        ip = self.svc.detect_ip()
        self.call_from_thread(self._region_hint, ip)

    def _region_hint(self, ip: str | None) -> None:
        hint = self.query_one("#region-hint", Static)
        current = self.a.country or ip
        if ip:
            hint.update(t("wz_region_ip", name=region.name(ip, self.a.lang), code=ip))
        if current and region.has_store(current) and "region" not in self.valid:
            self._choose_region(current)
        self._fill_regions(self.query_one("#region-search", Input).value or (current or ""))

    def _fill_regions(self, query: str) -> None:
        ol = self.query_one("#region-options", OptionList)
        ol.clear_options()
        codes = [c for c in (region.search(query, self.a.lang)[:12] if query else []) if region.has_store(c)]
        ol.add_options([Option(Text.assemble(region.label(c, self.a.lang), ("  " + c, "dim")), id=c) for c in codes])
        if codes:
            ol.highlighted = 0

    @on(Input.Submitted, "#region-search")
    def region_enter(self) -> None:
        """Enter in the search box picks the best match — no need to reach for the list."""
        ol = self.query_one("#region-options", OptionList)
        if ol.option_count:
            self._choose_region(ol.get_option_at_index(ol.highlighted or 0).id)

    @on(Input.Changed, "#region-search")
    def region_search(self, event: Input.Changed) -> None:
        self._fill_regions(event.value)

    @on(OptionList.OptionSelected, "#region-options")
    def region_picked(self, event: OptionList.OptionSelected) -> None:
        self._choose_region(event.option.id)

    def _choose_region(self, code: str) -> None:
        self.a.country = code
        config.cfg.country = code
        sample = (region.info(code) or {}).get("sample") or ["", ""]
        self.query_one("#region-status", Static).update(
            f"[$success]✓ {region.label(code, self.a.lang)}[/]  [dim]{t('wz_region_example', price=sample[0])}[/]")
        self._mark("region", True)

    @work(thread=True, exclusive=True, group="family")
    def find_family(self) -> None:
        fam = self.svc.family(self.a.steam_id)
        ids = [x for x in fam.get("member_steam_ids", []) if x != self.a.steam_id]
        names = self.svc.names(ids) if ids else {}
        self.call_from_thread(self._family_result, fam, ids, names)

    def _family_result(self, fam, ids, names) -> None:
        box = self.query_one("#family-found", Static)
        if fam:
            members = ", ".join(names.get(i) or i[-4:] for i in ids) or "—"
            box.update(f"[$success]✓ {fam.get('name')}[/]  [dim]{members}[/]\n{t('wz_family_auto')}")
        else:
            box.update(f"[dim]{t('wz_family_none')}[/]")

    @on(Button.Pressed, "#open-itad")
    def open_itad(self) -> None:
        self.svc.open_url(ITAD_URL)

    @on(Input.Changed, "#itad-key")
    def itad_changed(self, event: Input.Changed) -> None:
        key = event.value.strip()
        status = self.query_one("#itad-status", Static)
        if not key:
            status.update(f"[dim]{t('wz_itad_skip')}[/]")
            self._mark("itad", True)
            return
        if len(key) >= 30:
            self._mark("itad", False)
            status.update(f"[dim]{t('wz_checking')}[/]")
            self.validate_itad(key)

    @work(thread=True, exclusive=True, group="itad")
    def validate_itad(self, key: str) -> None:
        ok = self.svc.check_itad_key(key)
        self.call_from_thread(self._itad_result, key, ok)

    def _itad_result(self, key: str, ok: bool | None) -> None:
        status = self.query_one("#itad-status", Static)
        if ok:
            self.a.itad_key = key
            self.svc.save_secret("itad_api_key", key)
            status.update(f"[$success]✓ {t('wz_key_ok')}[/]")
        else:
            status.update(f"[$error]✗ {t('cfg_itad_invalid')}[/]" if ok is False else f"[$warning]! {t('dr_network')}[/]")
        self._mark("itad", True)          # optional step: never blocks

    def _read_prefs(self) -> None:
        f = config.cfg.profile.filters
        f.game_lang = self.query_one("#pref-game-lang", Select).value or ""
        f.deck = self.query_one("#pref-deck", Select).value or "any"
        f.adult = not self.query_one("#pref-adult", Switch).value
        f.early_access = "hide" if self.query_one("#pref-ea", Switch).value else "show"
        f.third_party = not self.query_one("#pref-third", Switch).value
        raw = self.query_one("#pref-budget", Input).value.strip().replace(",", ".")
        try:
            config.cfg.profile.budget = float(raw) if raw else None
        except ValueError:
            config.cfg.profile.budget = None
        try:
            config.cfg.profile.min_discount = max(0, min(99, int(self.query_one("#pref-min-discount", Input).value)))
        except ValueError:
            pass

    @on(Input.Submitted, "#seed-search")
    def seed_search(self, event: Input.Submitted) -> None:
        self.search_seeds(event.value)

    @work(thread=True, exclusive=True, group="seeds")
    def search_seeds(self, q: str) -> None:
        hits = self.svc.search_games(q) if q.strip() else []
        self.call_from_thread(self._seed_results, hits)

    def _seed_results(self, hits) -> None:
        ol = self.query_one("#seed-options", OptionList)
        ol.clear_options()
        ol.add_options([Option(name, id=str(aid)) for aid, name in hits])
        if hits:
            ol.highlighted = 0
            ol.focus()

    @on(OptionList.OptionSelected, "#seed-options")
    def seed_picked(self, event: OptionList.OptionSelected) -> None:
        aid = int(event.option.id)
        if aid not in self.a.seeds:
            self.a.seeds.append(aid)
            self._seed_names = getattr(self, "_seed_names", []) + [str(event.option.prompt)]
        self.query_one("#seed-chosen", Static).update("♥ " + " · ".join(self._seed_names))

    @on(RadioSet.Changed, "#channel")
    def channel_changed(self, event: RadioSet.Changed) -> None:
        ch = event.pressed.id.removeprefix("ch-")
        self.a.channel = "" if ch == "later" else ch
        self.query_one("#tg-box").display = ch == "telegram"
        self._mark("notify", ch != "telegram" or bool(self.a.telegram_chat))

    @on(Button.Pressed, "#open-botfather")
    def open_botfather(self) -> None:
        self.svc.open_url(BOTFATHER_URL)

    @on(Button.Pressed, "#tg-link")
    def tg_link(self) -> None:
        token = self.query_one("#tg-token", Input).value.strip()
        if token:
            self.query_one("#tg-status", Static).update(f"[dim]{t('wz_checking')}[/]")
            self.link_telegram(token)

    @work(thread=True, exclusive=True, group="telegram")
    def link_telegram(self, token: str) -> None:
        bot = self.svc.telegram_me(token)
        if not bot:
            self.call_from_thread(self._tg_status, f"[$error]✗ {t('tg_token_bad')}[/]")
            return
        self.call_from_thread(self._tg_status, f"[$success]✓ @{bot}[/]  {t('wz_tg_press_start', bot=bot)}")
        self.svc.open_url(f"https://t.me/{bot}")
        found = self.svc.telegram_wait(token)
        if not found:
            self.call_from_thread(self._tg_status, f"[$error]✗ {t('tg_no_start')}[/]")
            return
        self.a.telegram_token, self.a.telegram_chat = token, found["chat_id"]
        self.call_from_thread(self._tg_linked, found)

    def _tg_status(self, text: str) -> None:
        self.query_one("#tg-status", Static).update(text)

    def _tg_linked(self, found: dict) -> None:
        self._tg_status(f"[$success]✓ {t('tg_linked', name=found.get('name') or found['chat_id'])}[/]")
        self._mark("notify", True)

    def _summary(self) -> None:
        self.save()
        a = self.a
        lines = [f"[b]{a.user or a.steam_id}[/] · {region.label(a.country, a.lang) if a.country else '—'}",
                 t("wz_sum_family", v=t("cfg_auto") if a.family_auto else len(a.family)),
                 t("wz_sum_itad", v="✓" if a.itad_key else "—"),
                 t("wz_sum_notify", v=a.channel or t("wz_ch_later"))]
        if a.channel == "ntfy":
            n = config.cfg.profile.notify
            lines.append(t("ntfy_setup", url=f"{n.ntfy_server.rstrip('/')}/{n.ntfy_topic}"))
        if a.seeds:
            lines.append(t("wz_sum_seeds", n=len(a.seeds)))
        self.query_one("#done-summary", Static).update("\n".join(lines) + "\n\n" + t("wz_done_hint"))

    def save(self) -> None:
        """Persist everything the user confirmed (keys were saved as soon as they validated)."""
        c = config.cfg
        s, p = c.settings, c.profile
        a = self.a
        s.lang = a.lang
        p.steam_id, p.country = a.steam_id, a.country
        links = self.query_one("#family-links", Input).value.strip()
        if links:
            ids = [steamid.resolve(x, a.steam_key) for x in links.split()]
            p.family = [x for x in ids if x]
            a.family_auto = not p.family
        if a.seeds:
            p.seeds = list(dict.fromkeys(p.seeds + a.seeds))
        if a.channel:
            if a.channel == "telegram" and a.telegram_chat:
                self.svc.save_secret("telegram_token", a.telegram_token)
                p.notify.telegram_chat = a.telegram_chat
            if a.channel == "ntfy" and not p.notify.ntfy_topic:
                import secrets
                p.notify.ntfy_topic = f"sift-{secrets.token_hex(5)}"
            if a.channel not in p.notify.channels:
                p.notify.channels.append(a.channel)
        s.save()
        c.steam_id, c.country, c.lang, c.family = p.steam_id, p.country, a.lang or c.lang, list(p.family)

    @on(Button.Pressed, "#show")
    def show(self) -> None:
        self.exit("show")

    @on(Button.Pressed, "#exit")
    def leave(self) -> None:
        self.exit("exit")


def run_wizard(services: Services | None = None) -> str:
    return Wizard(services).run() or "exit"
