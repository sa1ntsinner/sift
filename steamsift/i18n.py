"""UI strings (RU / EN). `t("key", **kw)`; missing RU strings fall back to EN."""
from __future__ import annotations

from . import config

EN: dict[str, str] = {
    # header
    "owned": "owned", "family": "family", "wishlist": "wishlist", "hidden": "hidden", "taste": "taste",
    "budget": "budget", "no_itad": "no price history · sift config set itad-key",
    "ip_mismatch": "IP looks like {ip}; prices are for {country}", "dr_wishlist": "wishlist", "dr_family": "family",
    # sections
    "sec_wishlist": "wishlist on sale", "sec_picks": "picked for you", "sec_dlc": "dlc for your games",
    "sec_dna": "taste dna", "sec_built": "built from", "sec_family": "family · {name}", "sec_hidden": "hidden",
    "sec_config": "settings", "sec_profiles": "profiles", "sec_regions": "store regions",
    # columns
    "col_score": "score", "col_game": "game", "col_price": "price", "col_cut": "cut", "col_history": "history", "col_verdict": "verdict",
    "col_ends": "ends", "col_rev": "rev", "col_why": "why", "col_dlc": "dlc", "col_for": "for", "col_owner": "owner",
    "col_tag": "tag", "col_share": "share", "col_signal": "signal", "col_hours": "hours", "col_weight": "weight",
    "col_member": "member", "col_games": "games", "col_reason": "reason", "col_since": "since",
    "col_country": "country", "col_code": "code", "col_currency": "prices", "col_example": "example",
    # verdicts / cells
    "v_lowest": "★ lowest ever", "v_near": "◆ near low −{n}%", "v_was": "was −{n}%",
    "hours_short": "{n}h", "days_short": "{n}d",
    "why_like": "like {name}", "why_series": "{name} series",
    "note_unshared": "{owner} has it · not shareable",
    # footer & empty states
    "hint_click": "click a title to open", "hint_open": "sift open <#>", "hint_info": "sift info <game>",
    "hint_hide": "sift hide <#>",
    "scanned": "scanned {n} sales", "scanned_dlc": "scanned {n} DLC sales · DLC you already own may still appear",
    "wish_unavailable": "{n} wishlist games aren't sold in {country}",
    "empty_wish": "Nothing from your wishlist matches right now.", "empty_picks": "No picks matched your filters.",
    "empty_dlc": "No discounted DLC for games in your library or family right now.",
    "empty_family": "No Steam Family found. Add members: sift config set family <profile links…>",
    "empty_hidden": 'Nothing hidden. After a list: sift hide 14   (or sift hide "game name")',
    # spinners
    "sp_library": "reading library & taste…", "sp_sift": "sifting the sale…", "sp_history": "checking price history…",
    "sp_dlc": "scanning DLC sales…", "sp_lookup": "looking up…", "sp_dna": "building taste profile…",
    "sp_family": "reading family…", "sp_resolve": "checking profile…",
    # status / info
    "st_owned": "owned · {h}h", "st_family": "family · {owner}", "st_family_unshared": "{owner} has it, but it can't be shared",
    "st_wishlist": "in wishlist", "st_hidden": "⊘ hidden", "st_unavailable": "not sold in {country}",
    "free": "Free to play", "ends_in": "ends in", "not_purchasable": "not purchasable",
    "deepest": "deepest Steam cut ever −{n}%", "wait": "not on sale — wait", "match": "match",
    "affinity": "affinity", "quality": "quality", "why": "why", "tags": "tags", "history": "history",
    "reviews_of": "{pct}% of {n}",
    # dlc owners
    "own_you": "you · {h}h", "own_unplayed": "you · unplayed", "own_family": "family · {owner}",
    # hide
    "hidden_ok": "won't be recommended again", "hidden_taste": "and fewer games like it",
    "hidden_owned": "excluded only", "reason_taste": "not my taste", "reason_owned": "have it / skip",
    "restore_hint": "restore: sift unhide <#>  ·  sift unhide all", "restored_n": "restored {n} game(s)",
    "restored": "restored {name}", "not_hidden": "not hidden: {t}",
    # family view
    "family_note": "{n} shared games you don't own are hidden (show them: sift config set family on).",
    "family_unshared": "{n} of them can't be shared (publisher setting) and stay recommendable.",
    "family_private": "private?", "you": "you", "family_src_client": "read from your Steam client",
    "family_src_manual": "from your settings",
    # dna
    "dna_note": "+ {n} wishlist games as intent · weights = log(1+h) × recency (½-life 1y) + last-2-weeks boost · "
                "dropped (<1h) and ⊘ hidden games count negative · TF-IDF tag space",
    "dna_no_playtime": "Playtime is hidden in your Steam privacy settings — taste uses ownership & wishlist only.",
    # errors
    "err_no_last": "No previous results. Run `sift` first.", "err_range": "#{n} is out of range (1–{max}).",
    "err_not_found": "No Steam game found for “{q}”.", "err_not_sold": "{name} isn't sold in {country}.",
    "err_not_configured": "sift isn't set up yet.",
    "setup_steps": "  1. sift config set steam <your profile link>\n"
                   "  2. sift config set steam-key   (get one at https://steamcommunity.com/dev/apikey)\n"
                   "  3. sift config set country <your store country>",
    "err_no_country": "Store country isn't set. This IP looks like {name} — if your Steam account is from there: "
                      "sift config set country {ip}  (otherwise name your account's country; VPN/travel can mislead)",
    "err_no_country_noip": "Store country isn't set: sift config set country <country>",
    "err_no_store": "Steam doesn't sell games in {country}. Set the region you buy in: sift config set country <code>",
    "err_private": "Your game list is private, so taste & exclusions can't work. Steam → Profile → Edit → "
                   "Privacy → Game details: Public  (https://steamcommunity.com/my/edit/settings)",
    "err_bad_profile": "Couldn't recognise a Steam profile in “{q}”.", "err_need_key_vanity":
        "Custom profile names need the Steam API key first (sift config set steam-key) — or paste the /profiles/7656… link.",
    "opened": "opened {name}",
    # config
    "cfg_saved": "saved", "cfg_unknown_key": "unknown setting “{k}”. Available: {keys}",
    "cfg_country_set": "store country: {label}", "cfg_country_ambiguous": "“{q}” matches several countries: {opts}",
    "cfg_country_unknown": "unknown country “{q}”. Try: sift config regions {q}",
    "cfg_profile_set": "profile: {name} ({id})", "cfg_key_prompt": "paste the key (input hidden): ",
    "cfg_key_saved": "key saved to {where}", "cfg_key_removed": "key removed",
    "cfg_key_invalid": "Steam rejected this key — check it at https://steamcommunity.com/dev/apikey",
    "cfg_family_auto": "family: read from the Steam client", "cfg_family_set": "family: {n} member(s)",
    "cfg_budget_off": "budget: off", "cfg_budget_set": "budget: {v}", "cfg_lang_set": "language: {v}",
    "cfg_min_set": "minimum discount: {v}%", "cfg_cache_cleared": "cleared {n} cached responses",
    "cfg_paths": "files", "cfg_not_set": "not set", "cfg_auto": "auto",
    "pf_created": "profile “{name}” created — set it up with: sift -p {name} config set steam <link>",
    "pf_active": "active profile: {name}", "pf_removed": "profile “{name}” removed",
    "pf_unknown": "no profile “{name}”", "pf_last": "can't remove the only profile",
    "regions_hint": "groups: USD regions charge different prices (MENA, CIS, LATAM, South Asia).",
}

RU: dict[str, str] = {
    "owned": "в библиотеке", "family": "в семье", "wishlist": "в вишлисте", "hidden": "скрыто", "taste": "вкус",
    "budget": "бюджет", "no_itad": "нет истории цен · sift config set itad-key",
    "ip_mismatch": "IP-адрес: {ip}, цены — для региона {country}", "dr_wishlist": "вишлист", "dr_family": "семья",
    "sec_wishlist": "вишлист со скидкой", "sec_picks": "подобрано для тебя", "sec_dlc": "dlc к твоим играм",
    "sec_dna": "вкус", "sec_built": "из чего собран", "sec_family": "семья · {name}", "sec_hidden": "скрытые",
    "sec_config": "настройки", "sec_profiles": "профили", "sec_regions": "регионы магазина",
    "col_score": "оценка", "col_game": "игра", "col_price": "цена", "col_cut": "скидка", "col_history": "история", "col_verdict": "вердикт",
    "col_ends": "до", "col_rev": "отз.", "col_why": "почему", "col_dlc": "дополнение", "col_for": "к игре",
    "col_owner": "чья", "col_tag": "тег", "col_share": "доля", "col_signal": "сигнал", "col_hours": "часы",
    "col_weight": "вес", "col_member": "участник", "col_games": "игр", "col_reason": "причина",
    "col_since": "когда", "col_country": "страна", "col_code": "код", "col_currency": "цены",
    "col_example": "пример",
    "v_lowest": "★ рекорд", "v_near": "◆ близко к −{n}%", "v_was": "было −{n}%",
    "hours_short": "{n}ч", "days_short": "{n}д",
    "why_like": "как {name}", "why_series": "серия {name}",
    "note_unshared": "есть у {owner} · не делится",
    "hint_click": "клик по названию — открыть", "hint_open": "sift open <#>", "hint_info": "sift info <игра>",
    "hint_hide": "sift hide <#>",
    "scanned": "просмотрено скидок: {n}",
    "scanned_dlc": "просмотрено DLC: {n} · уже купленные DLC могут попадаться",
    "wish_unavailable": "игр из вишлиста не продаётся в регионе {country}: {n}",
    "empty_wish": "Сейчас ничего из вишлиста не подходит.", "empty_picks": "Под твои фильтры ничего не нашлось.",
    "empty_dlc": "Сейчас нет скидок на DLC к играм из твоей библиотеки или семьи.",
    "empty_family": "Семья не найдена. Добавь участников: sift config set family <ссылки на профили…>",
    "empty_hidden": 'Ничего не скрыто. После списка: sift hide 14   (или sift hide "название")',
    "sp_library": "читаю библиотеку и вкус…", "sp_sift": "просеиваю распродажу…",
    "sp_history": "сверяю историю цен…", "sp_dlc": "ищу скидки на DLC…", "sp_lookup": "ищу…",
    "sp_dna": "собираю профиль вкуса…", "sp_family": "читаю семью…", "sp_resolve": "проверяю профиль…",
    "st_owned": "есть · {h}ч", "st_family": "в семье · {owner}",
    "st_family_unshared": "есть у {owner}, но в семье не делится", "st_wishlist": "в вишлисте",
    "st_hidden": "⊘ скрыта", "st_unavailable": "не продаётся в регионе {country}",
    "free": "Бесплатно", "ends_in": "до конца", "not_purchasable": "нельзя купить",
    "deepest": "лучшая скидка в Steam за всё время −{n}%", "wait": "сейчас без скидки — подожди",
    "match": "совпадение", "affinity": "вкус", "quality": "качество", "why": "почему", "tags": "теги",
    "history": "история", "reviews_of": "{pct}% из {n}",
    "own_you": "ты · {h}ч", "own_unplayed": "ты · не играл", "own_family": "семья · {owner}",
    "hidden_ok": "больше не будет рекомендоваться", "hidden_taste": "и похожих станет меньше",
    "hidden_owned": "просто скрыта", "reason_taste": "не мой вкус", "reason_owned": "уже есть / не сейчас",
    "restore_hint": "вернуть: sift unhide <#>  ·  sift unhide all", "restored_n": "возвращено игр: {n}",
    "restored": "возвращена {name}", "not_hidden": "не скрыта: {t}",
    "family_note": "{n} игр семьи, которых нет у тебя, скрыты (показать: sift config set family on).",
    "family_unshared": "Из них {n} не делятся (так решил издатель) — их рекомендовать можно.",
    "family_private": "скрыто?", "you": "ты", "family_src_client": "взято из клиента Steam",
    "family_src_manual": "из настроек",
    "dna_note": "+ {n} игр вишлиста как намерение · вес = log(1+ч) × свежесть (½ за год) + бонус за 2 недели · "
                "брошенные (<1ч) и ⊘ скрытые игры идут в минус · пространство тегов TF-IDF",
    "dna_no_playtime": "Время в играх скрыто настройками приватности — вкус считается по владению и вишлисту.",
    "err_no_last": "Нет прошлого списка. Сначала запусти `sift`.", "err_range": "#{n} вне списка (1–{max}).",
    "err_not_found": "Не нашёл игру «{q}» в Steam.", "err_not_sold": "{name} не продаётся в регионе {country}.",
    "err_not_configured": "sift ещё не настроен.",
    "setup_steps": "  1. sift config set steam <ссылка на профиль>\n"
                   "  2. sift config set steam-key   (ключ: https://steamcommunity.com/dev/apikey)\n"
                   "  3. sift config set country <страна магазина>",
    "err_no_country": "Не задана страна магазина. По IP это {name} — если твой аккаунт Steam оттуда: "
                      "sift config set country {ip}  (иначе укажи страну аккаунта; VPN и поездки сбивают определение)",
    "err_no_country_noip": "Не задана страна магазина: sift config set country <страна>",
    "err_no_store": "Steam не продаёт игры в регионе {country}. Укажи регион, где покупаешь: sift config set country <код>",
    "err_private": "Список игр скрыт, вкус и исключения не работают. Steam → Профиль → Редактировать → "
                   "Приватность → Игровые данные: Открытые  (https://steamcommunity.com/my/edit/settings)",
    "err_bad_profile": "Не узнал профиль Steam в «{q}».",
    "err_need_key_vanity": "Для ника нужен API-ключ (sift config set steam-key) — или вставь ссылку /profiles/7656….",
    "opened": "открыто: {name}",
    "cfg_saved": "сохранено", "cfg_unknown_key": "нет настройки «{k}». Доступно: {keys}",
    "cfg_country_set": "страна магазина: {label}", "cfg_country_ambiguous": "«{q}» подходит под несколько стран: {opts}",
    "cfg_country_unknown": "неизвестная страна «{q}». Попробуй: sift config regions {q}",
    "cfg_profile_set": "профиль: {name} ({id})", "cfg_key_prompt": "вставь ключ (ввод скрыт): ",
    "cfg_key_saved": "ключ сохранён: {where}", "cfg_key_removed": "ключ удалён",
    "cfg_key_invalid": "Steam не принял ключ — проверь на https://steamcommunity.com/dev/apikey",
    "cfg_family_auto": "семья: из клиента Steam", "cfg_family_set": "семья: участников {n}",
    "cfg_budget_off": "бюджет: выключен", "cfg_budget_set": "бюджет: {v}", "cfg_lang_set": "язык: {v}",
    "cfg_min_set": "минимальная скидка: {v}%", "cfg_cache_cleared": "очищено ответов в кэше: {n}",
    "cfg_paths": "файлы", "cfg_not_set": "не задано", "cfg_auto": "авто",
    "pf_created": "профиль «{name}» создан — настрой: sift -p {name} config set steam <ссылка>",
    "pf_active": "активный профиль: {name}", "pf_removed": "профиль «{name}» удалён",
    "pf_unknown": "нет профиля «{name}»", "pf_last": "нельзя удалить единственный профиль",
    "regions_hint": "у долларовых регионов разные цены (MENA, CIS, LATAM, South Asia).",
}

EN.update({
    # cards & events
    "ev_wish_target": "Your target price", "ev_wish_lowest": "Wishlist at its lowest ever", "ev_ending": "Last chance",
    "ev_pick_strong": "You'll like this", "ev_dlc_lowest": "DLC at its lowest", "ev_sale_start": "A Steam sale started",
    "ev_top": "Picked for you", "ends_hours": "{n}h left", "ends_days": "{n}d left",
    "reviews_short": "👍 {pct}% of {n}", "why_you": "Why you", "note_target": "target reached",
    "note_elsewhere": "{shop} is {pct}% cheaper", "note_account": "needs {name}",
    "note_wait": "{sale} in {days}d", "sale_winter": "Winter Sale", "sale_spring": "Spring Sale",
    "sale_summer": "Summer Sale", "sale_autumn": "Autumn Sale", "digest_title": "sift \u00b7 {n} deals for you",
    "test_note": "test card", "test_title": "sift test",
    # telegram
    "tg_cmd_top": "Best picks right now", "tg_cmd_wishlist": "Wishlist on sale", "tg_cmd_dlc": "DLC for your games",
    "tg_cmd_info": "Price & match for a game", "tg_cmd_hidden": "Games you've hidden",
    "tg_cmd_budget": "Set budget (number or off)", "tg_cmd_pause": "Pause alerts for N days",
    "tg_cmd_resume": "Resume alerts", "tg_cmd_help": "What I can do",
    "tg_more": "More", "tg_hide": "Not for me", "tg_cancel": "Cancel", "tg_hidden_undo": "Hidden \u00b7 undo",
    "tg_why_hide": "Why hide it?", "tg_hidden_ok": "Hidden", "tg_restored": "Restored",
    "tg_help": "<b>sift</b> \u2014 Steam deals that match your taste\n\n/top \u2014 best picks now\n/wishlist \u2014 wishlist on sale\n"
               "/dlc \u2014 DLC for your games\n/info &lt;game&gt; \u2014 price, history &amp; match\n/hidden \u2014 hidden games\n"
               "/budget 15 \u2014 max price (or off)\n/pause 7 \u2014 pause alerts \u00b7 /resume\n\n"
               "Buttons under cards: \U0001f6d2 store \u00b7 \u2139\ufe0f details \u00b7 \u2298 don't recommend",
    "tg_info_usage": "Usage: /info elden ring", "tg_paused": "Alerts paused for {n} days", "tg_resumed": "Alerts resumed",
    "tg_setup_1": "1. In Telegram, @BotFather opens \u2014 send /newbot, pick any name, copy the token.",
    "tg_setup_2": "2. Open https://t.me/{bot} and press Start \u2014 I'll catch it automatically.",
    "tg_token_prompt": "bot token (hidden): ", "tg_token_bad": "Telegram rejected this token",
    "tg_bot_ok": "bot @{bot} found", "tg_waiting": "waiting for you to press Start in the bot\u2026",
    "tg_no_start": "Didn't see /start in time \u2014 run the setup again", "tg_linked": "linked to {name}",
    "dc_setup": "Discord: channel settings \u2192 Integrations \u2192 Webhooks \u2192 New webhook \u2192 Copy URL.",
    "dc_prompt": "webhook URL (hidden): ", "dc_bad": "That webhook URL doesn't work",
    "ntfy_setup": "Subscribe in the ntfy app (or browser): {url}", "email_to_prompt": "send to",
    # notify CLI
    "sec_notify": "notifications", "n_channels": "channels", "n_mode": "mode", "n_quiet": "quiet hours",
    "n_events": "events", "n_schedule": "schedule", "n_paused": "paused until", "n_pending": "in digest queue",
    "n_none": "none \u2014 sift notify setup telegram",
    "n_hint": "sift notify setup <telegram|discord|ntfy|desktop|email> \u00b7 test \u00b7 run --dry-run \u00b7 enable \u00b7 actions",
    "n_test_sent": "sent \u201c{name}\u201d to {channels}", "n_skipped_paused": "notifications are paused (sift notify resume)",
    "n_skipped_no_channels": "no channels yet: sift notify setup telegram",
    "n_dry": "{n} event(s) would be sent", "n_ran": "{events} new \u00b7 {sent} sent \u00b7 {queued} queued \u00b7 {digest} in digest",
    "n_enabled": "scheduled every {every} min", "n_enable_failed": "couldn't schedule", "n_disabled": "schedule removed",
    "n_offer_enable": "Run automatically: sift notify enable   (or keep `sift watch` open)",
    "n_actions_written": "workflow written: {path}",
    "n_actions_secrets": "  Push it to a private GitHub repo and add these Actions secrets:",
    "watch_start": "watching: a scan every {every} min \u00b7 Ctrl+C to stop",
    # targets / calendar
    "sec_targets": "price targets", "target_col": "notify at", "target_any_low": "lowest ever",
    "target_hint": "sift target <#|game> <price|lowest|off>", "target_set": "\U0001f3af {name}: alert at \u2264 {price}",
    "target_lowest": "\U0001f3af {name}: alert at its lowest ever", "target_removed": "target removed: {name}",
    "sec_calendar": "steam sales & fests", "cal_event": "event", "cal_dates": "dates", "cal_now": "now",
    "cal_in_days": "in {n}d", "cal_source": "source: Valve's partner calendar \u00b7 \u2605 = matches your taste",
    "cal_running": "{sale} is on until {end} \u2014 the biggest discounts of the season",
    "cal_next": "{sale} in {days} days ({start} \u2013 {end}) \u2014 without a record low, waiting usually pays",
    "cal_fest": "{name} {when} \u2014 your genre", "sp_calendar": "reading the sale calendar\u2026",
    # doctor
    "sec_doctor": "doctor", "sp_doctor": "checking everything\u2026", "sp_test": "sending a test card\u2026",
    "dr_config": "settings file", "dr_steam_key": "Steam API key", "dr_profile": "Steam profile",
    "dr_game_details": "game details", "dr_region": "store region", "dr_store": "Steam store",
    "dr_notify": "notifications", "dr_schedule": "schedule", "dr_db": "database", "dr_valid": "valid",
    "dr_rejected": "rejected", "dr_network": "network problem \u2014 try again",
    "dr_private_profile": "{name}: profile is private",
    "dr_games_hidden": "hidden \u2014 set Game details: Public", "dr_playtime_hidden": "{n} games, playtime hidden",
    "dr_games_n": "{n} games with playtime", "dr_wishlist_empty": "empty or private",
    "dr_store_ok": "reachable \u00b7 {n} deals on the first page", "dr_no_family": "no Steam Family found (optional)",
    "dr_itad_optional": "not set \u2014 optional, adds \u201c\u2605 lowest ever\u201d verdicts", "dr_notify_off": "off (optional)",
    "dr_tg_incomplete": "token or chat missing", "dr_enabled": "enabled", "dr_schedule_off": "not scheduled",
    "dr_summary": "{ok} ok \u00b7 {warn} warnings \u00b7 {fail} problems",
    # config help
    "sec_config_keys": "settings (sift config set <key> <value>)", "cfg_more": "all settings: sift config help",
    "cfg_itad_invalid": "IsThereAnyDeal rejected this key \u2014 https://isthereanydeal.com/apps/my/",
    "set_bool": "use on / off", "set_choice": "choose: {opts}", "set_number": "a number from {lo} to {hi}",
    "set_time": "use HH:MM, e.g. 19:00", "set_quiet": "use HH:MM-HH:MM, e.g. 23:00-09:00, or off",
    "hint_setup": "Easiest: run `sift setup` for a guided setup.",
    "h_steam": "your profile link, nickname or SteamID", "h_country": "store country of your Steam account",
    "h_lang": "interface language: ru | en | auto", "h_budget": "max price in your store's currency, or off",
    "h_min_discount": "minimum discount, %", "h_family": "family member links, or auto (Steam client)",
    "h_steam_key": "Steam Web API key (input hidden)", "h_itad_key": "IsThereAnyDeal key \u2014 price history",
    "h_game_lang": "any | subs [language] | audio [language] \u2014 e.g. audio russian",
    "h_deck": "Steam Deck: any | playable | verified", "h_platforms": "any | windows, mac, linux",
    "h_adult": "show adult-only games: on | off", "h_early_access": "early access: show | hide",
    "h_vr": "include VR-only games: on | off", "h_third_party": "allow EA / Ubisoft / Rockstar accounts: on | off",
    "h_exclude_tags": "never recommend these tags: Anime, Horror \u2026", "h_min_reviews": "minimum number of reviews",
    "h_min_positive": "minimum % positive reviews", "h_explore": "0 familiar \u2026 1 adventurous",
    "h_elsewhere": "show cheaper official stores: auto | on | off",
    "h_channels": "telegram, discord, ntfy, desktop, email", "h_notify_mode": "digest | instant",
    "h_digest_time": "daily digest time, HH:MM", "h_quiet": "no instant alerts, e.g. 23:00-09:00",
    "h_events": "wish_lowest, wish_target, pick_strong, ending, dlc_lowest, sale_start",
    "h_min_score": "picks must score at least this to alert", "h_every": "minutes between scheduled scans",
    "h_ntfy_topic": "ntfy topic (keep it unguessable)", "h_ntfy_server": "ntfy server URL",
    "h_email_to": "send digests to", "h_smtp_host": "SMTP server", "h_smtp_port": "SMTP port (587 / 465)",
    "h_smtp_user": "SMTP login", "h_smtp_password": "SMTP / app password (hidden)",
    "h_discord_webhook": "Discord webhook URL (hidden)", "h_telegram_token": "Telegram bot token (hidden)",
    "h_telegram_chat": "Telegram chat id (set automatically by setup)",
    # TUI app
    "err_unknown_cmd": "no command “{cmd}”", "hint_help": "all commands: sift help",
    "ui_updating": "updating…", "ui_refresh_failed": "couldn't refresh, showing saved data",
    "h_covers": "cover art in the app: auto (real pictures where the terminal can) | sixel | blocks | off",
    "ui_tab_picks": "For you", "ui_tab_wish": "Wishlist", "ui_tab_hidden": "Hidden", "ui_tab_taste": "Taste",
    "ui_k_quit": "Quit", "ui_k_open": "Open", "ui_k_hide": "Hide", "ui_k_undo": "Undo", "ui_k_search": "Search",
    "ui_k_filters": "Filters", "ui_k_sort": "Sort", "ui_k_refresh": "Refresh", "ui_k_theme": "Theme",
    "ui_search_ph": "search by title\u2026", "ui_nothing": "Nothing here with these filters.",
    "ui_hide_question": "Don't recommend it again \u2014 why?", "ui_undo_hint": "press u to undo", "ui_open": "open store",
    "ui_filters": "filters", "ui_filters_hint": "only this view \u00b7 permanent ones: sift config",
    "ui_apply": "Apply", "ui_filters_off": "filters off", "ui_f_lowest": "\u2605 only record lows",
    "ui_f_budget": "within my budget", "ui_f_deck": "works on Steam Deck", "ui_f_lang": "in my language",
    "ui_f_no_ea": "no early access", "ui_sorted": "sorted by {by}", "ui_sort_score": "match",
    "ui_sort_price": "price", "ui_sort_cut": "discount", "ui_sort_ends": "ending soon",
    # wizard
    "wz_back": "\u2190 Back", "wz_next": "Next \u2192", "wz_checking": "checking\u2026", "wz_optional": "optional",
    "wz_welcome": "sift finds the Steam deals that fit your taste \u2014 not just the biggest discounts.\n"
                  "Setup takes about 3 minutes. Keys stay on this computer, in the system keychain.\n\nLanguage:",
    "wz_key_title": "Steam Web API key",
    "wz_key_help": "It lets sift read your library and playtime. Open the page, log in, type any domain "
                   "(e.g. localhost), agree and copy the 32-character key.",
    "wz_open_key_page": "Open the key page \u2197", "wz_key_ok": "key works", "wz_key_len": "{n}/32 characters",
    "wz_profile_title": "Your Steam profile",
    "wz_profile_help": "Paste a profile link, nickname, SteamID or friend code \u2014 anything works.",
    "wz_is_you": "{name} \u2014 that's you", "wz_games_n": "{n} games", "wz_games_hidden": "games hidden",
    "wz_wishlist_n": "{n} in wishlist",
    "wz_privacy_title": "Privacy check", "wz_open_privacy": "Open privacy settings \u2197", "wz_recheck": "Check again",
    "wz_pv_profile": "profile is public", "wz_pv_fix_profile": "My Profile: Public",
    "wz_pv_games": "game details visible ({n} games)", "wz_pv_fix_games": "Game details: Public",
    "wz_pv_playtime": "playtime visible", "wz_pv_fix_playtime": "untick \u201cAlways keep my total playtime private\u201d",
    "wz_pv_wishlist": "wishlist visible ({n})", "wz_pv_fix_wishlist": "optional",
    "wz_region_title": "Store region",
    "wz_region_help": "Prices and availability follow your Steam account's country (not your IP). "
                      "Countries paying in $ still differ: MENA, CIS, LATAM, South Asia, US.",
    "wz_region_ip": "Your IP looks like {name} ({code}). Different account country? Search below.",
    "wz_region_search": "country name or code\u2026", "wz_region_example": "prices look like {price}",
    "wz_family_title": "Steam Family", "wz_family_auto": "Games your family can share are excluded automatically.",
    "wz_family_none": "No family found in the Steam client \u2014 paste member links below, or skip.",
    "wz_family_manual": "Members (optional, space-separated):",
    "wz_itad_title": "Price history (optional)",
    "wz_itad_help": "A free IsThereAnyDeal key adds \u201c\u2605 lowest ever / was \u221290%\u201d to every deal. "
                    "Open the page, create an app, copy its API key.",
    "wz_open_itad": "Open IsThereAnyDeal \u2197", "wz_itad_skip": "skipped \u2014 you can add it later",
    "wz_prefs_title": "Preferences", "wz_pref_game_lang": "Games in my language",
    "wz_any": "any", "wz_subs": "at least subtitles", "wz_audio": "voice-over",
    "wz_pref_adult": "Hide adult-only games", "wz_pref_ea": "Hide early access",
    "wz_pref_third": "Hide games needing EA/Ubisoft/\u2026 accounts", "wz_pref_budget": "Budget (store currency)",
    "wz_pref_min_discount": "Minimum discount, %",
    "wz_seeds_title": "A few favourites", "wz_seeds_search": "type a game and press Enter\u2026",
    "wz_seeds_help": "Your Steam history is short, so tell sift 3\u20135 games you love (from any platform).",
    "wz_notify_title": "Alerts", "wz_notify_help": "Get the best deals delivered \u2014 record lows from your wishlist, "
                                                  "strong picks, last chances. One message a day by default.",
    "wz_ch_desktop": "Windows notifications", "wz_ch_later": "Later",
    "wz_tg_step1": "Create your personal bot: open @BotFather \u2192 /newbot \u2192 any name \u2192 copy the token here.",
    "wz_open_botfather": "Open @BotFather \u2197", "wz_tg_link": "Link my bot",
    "wz_tg_press_start": "now press Start in @{bot} \u2014 Telegram is open",
    "wz_done_title": "All set", "wz_show": "Show my deals", "wz_exit": "Exit",
    "wz_done_hint": "Later: sift \u00b7 sift macro \u00b7 sift doctor \u00b7 sift notify enable \u00b7 sift config help",
    "wz_sum_family": "family: {v}", "wz_sum_itad": "price history: {v}", "wz_sum_notify": "alerts: {v}",
    "wz_sum_seeds": "favourites: {n}",
})

RU.update({
    "ev_wish_target": "\u0422\u0432\u043e\u044f \u0446\u0435\u043b\u0435\u0432\u0430\u044f \u0446\u0435\u043d\u0430", "ev_wish_lowest": "Рекорд в вишлисте", "ev_ending": "Последний шанс",
    "ev_pick_strong": "Тебе понравится", "ev_dlc_lowest": "DLC по рекордной цене",
    "ev_sale_start": "Началась распродажа Steam", "ev_top": "Подобрано для тебя",
    "ends_hours": "ещё {n} ч", "ends_days": "ещё {n} дн.",
    "reviews_short": "\U0001f44d {pct}% из {n}", "why_you": "Почему тебе", "note_target": "цель достигнута",
    "note_elsewhere": "в {shop} на {pct}% дешевле", "note_account": "нужен {name}",
    "note_wait": "{sale} через {days} дн.", "sale_winter": "Зимняя распродажа", "sale_spring": "Весенняя распродажа",
    "sale_summer": "Летняя распродажа", "sale_autumn": "Осенняя распродажа",
    "digest_title": "sift · {n} предложений для тебя", "test_note": "тестовая карточка", "test_title": "sift · тест",
    "tg_cmd_top": "Лучшее для тебя сейчас", "tg_cmd_wishlist": "Вишлист со скидкой", "tg_cmd_dlc": "DLC к твоим играм",
    "tg_cmd_info": "Цена и совпадение для игры", "tg_cmd_hidden": "Скрытые игры",
    "tg_cmd_budget": "Бюджет (число или off)", "tg_cmd_pause": "Пауза уведомлений на N дней",
    "tg_cmd_resume": "Включить уведомления", "tg_cmd_help": "Что я умею",
    "tg_more": "Подробнее", "tg_hide": "Не моё", "tg_cancel": "Отмена", "tg_hidden_undo": "Скрыто · вернуть",
    "tg_why_hide": "Почему скрыть?", "tg_hidden_ok": "Скрыто", "tg_restored": "Возвращено",
    "tg_help": "<b>sift</b> — скидки Steam под твой вкус\n\n/top — лучшее сейчас\n/wishlist — вишлист со скидкой\n"
               "/dlc — DLC к твоим играм\n/info &lt;игра&gt; — цена, история и совпадение\n/hidden — скрытые игры\n"
               "/budget 15 — максимальная цена (или off)\n/pause 7 — пауза · /resume\n\n"
               "Кнопки под карточками: \U0001f6d2 магазин · \u2139\ufe0f подробнее · ⊘ больше не рекомендовать",
    "tg_info_usage": "Пример: /info elden ring", "tg_paused": "Уведомления на паузе {n} дн.",
    "tg_resumed": "Уведомления снова включены",
    "tg_setup_1": "1. Откроется @BotFather в Telegram — отправь /newbot, придумай любое имя и скопируй токен.",
    "tg_setup_2": "2. Открой https://t.me/{bot} и нажми Start — я поймаю это сам.",
    "tg_token_prompt": "токен бота (ввод скрыт): ", "tg_token_bad": "Telegram не принял токен",
    "tg_bot_ok": "бот @{bot} найден", "tg_waiting": "жду, пока ты нажмёшь Start в боте…",
    "tg_no_start": "Не дождался /start — запусти настройку ещё раз", "tg_linked": "привязан к {name}",
    "dc_setup": "Discord: настройки канала → Интеграция → Вебхуки → Новый вебхук → Копировать URL.",
    "dc_prompt": "URL вебхука (ввод скрыт): ", "dc_bad": "Этот вебхук не работает",
    "ntfy_setup": "Подпишись в приложении ntfy (или в браузере): {url}", "email_to_prompt": "куда отправлять",
    "sec_notify": "уведомления", "n_channels": "каналы", "n_mode": "режим", "n_quiet": "тихие часы",
    "n_events": "события", "n_schedule": "расписание", "n_paused": "пауза до", "n_pending": "в очереди дайджеста",
    "n_none": "нет — sift notify setup telegram",
    "n_hint": "sift notify setup <telegram|discord|ntfy|desktop|email> · test · run --dry-run · enable · actions",
    "n_test_sent": "«{name}» отправлено в {channels}", "n_skipped_paused": "уведомления на паузе (sift notify resume)",
    "n_skipped_no_channels": "каналов пока нет: sift notify setup telegram",
    "n_dry": "будет отправлено событий: {n}",
    "n_ran": "новых {events} · отправлено {sent} · в очередь {queued} · в дайджесте {digest}",
    "n_enabled": "запуск каждые {every} мин", "n_enable_failed": "не удалось запланировать",
    "n_disabled": "расписание удалено",
    "n_offer_enable": "Автоматически: sift notify enable   (или держи открытым `sift watch`)",
    "n_actions_written": "workflow записан: {path}",
    "n_actions_secrets": "  Залей его в приватный репозиторий GitHub и добавь секреты Actions:",
    "watch_start": "слежу: проверка каждые {every} мин · Ctrl+C — стоп",
    "sec_targets": "целевые цены", "target_col": "сообщить при", "target_any_low": "рекорде",
    "target_hint": "sift target <#|игра> <цена|lowest|off>", "target_set": "\U0001f3af {name}: сообщу при ≤ {price}",
    "target_lowest": "\U0001f3af {name}: сообщу при рекордной цене", "target_removed": "цель снята: {name}",
    "sec_calendar": "распродажи и фестивали steam", "cal_event": "событие", "cal_dates": "даты", "cal_now": "сейчас",
    "cal_in_days": "через {n} дн.", "cal_source": "источник: календарь Valve для партнёров · ★ — твой жанр",
    "cal_running": "Идёт {sale} до {end} — самые глубокие скидки сезона",
    "cal_next": "{sale} через {days} дн. ({start} – {end}) — если сейчас не рекорд, лучше подождать",
    "cal_fest": "{name} {when} — твой жанр", "sp_calendar": "читаю календарь распродаж…",
    "sec_doctor": "диагностика", "sp_doctor": "проверяю всё…", "sp_test": "отправляю тестовую карточку…",
    "dr_config": "файл настроек", "dr_steam_key": "ключ Steam API", "dr_profile": "профиль Steam",
    "dr_game_details": "игровые данные", "dr_region": "регион магазина", "dr_store": "магазин Steam",
    "dr_notify": "уведомления", "dr_schedule": "расписание", "dr_db": "база данных", "dr_valid": "работает",
    "dr_rejected": "отклонён", "dr_network": "проблема с сетью — попробуй ещё раз",
    "dr_private_profile": "{name}: профиль закрыт", "dr_games_hidden": "скрыты — Игровые данные: Открытые",
    "dr_playtime_hidden": "{n} игр, время скрыто", "dr_games_n": "{n} игр со временем",
    "dr_wishlist_empty": "пуст или скрыт", "dr_store_ok": "доступен · {n} скидок на первой странице",
    "dr_no_family": "семья Steam не найдена (необязательно)",
    "dr_itad_optional": "не задан — необязательно, добавит вердикты «★ рекорд»",
    "dr_notify_off": "выключены (необязательно)",
    "dr_tg_incomplete": "нет токена или чата", "dr_enabled": "включено", "dr_schedule_off": "не запланировано",
    "dr_summary": "в порядке: {ok} · предупреждений: {warn} · проблем: {fail}",
    "sec_config_keys": "настройки (sift config set <ключ> <значение>)", "cfg_more": "все настройки: sift config help",
    "cfg_itad_invalid": "IsThereAnyDeal не принял ключ — https://isthereanydeal.com/apps/my/",
    "set_bool": "укажи on / off", "set_choice": "варианты: {opts}", "set_number": "число от {lo} до {hi}",
    "set_time": "формат ЧЧ:ММ, например 19:00", "set_quiet": "формат ЧЧ:ММ-ЧЧ:ММ, например 23:00-09:00, или off",
    "hint_setup": "Проще всего: `sift setup` — пошаговая настройка.",
    "h_steam": "ссылка на профиль, ник или SteamID", "h_country": "страна магазина твоего аккаунта Steam",
    "h_lang": "язык интерфейса: ru | en | auto", "h_budget": "максимальная цена в валюте магазина, или off",
    "h_min_discount": "минимальная скидка, %", "h_family": "ссылки на участников семьи, или auto (из клиента)",
    "h_steam_key": "ключ Steam Web API (ввод скрыт)", "h_itad_key": "ключ IsThereAnyDeal — история цен",
    "h_game_lang": "any | subs [язык] | audio [язык] — например audio russian",
    "h_deck": "Steam Deck: any | playable | verified", "h_platforms": "any | windows, mac, linux",
    "h_adult": "показывать игры 18+: on | off", "h_early_access": "ранний доступ: show | hide",
    "h_vr": "включать VR-only игры: on | off", "h_third_party": "разрешать аккаунты EA / Ubisoft / Rockstar: on | off",
    "h_exclude_tags": "никогда не советовать теги: Anime, Horror …", "h_min_reviews": "минимум отзывов",
    "h_min_positive": "минимум % положительных отзывов", "h_explore": "0 — привычное … 1 — новое",
    "h_elsewhere": "показывать официальные магазины дешевле: auto | on | off",
    "h_channels": "telegram, discord, ntfy, desktop, email", "h_notify_mode": "digest | instant",
    "h_digest_time": "время дайджеста, ЧЧ:ММ", "h_quiet": "без мгновенных уведомлений, например 23:00-09:00",
    "h_events": "wish_lowest, wish_target, pick_strong, ending, dlc_lowest, sale_start",
    "h_min_score": "минимальная оценка подборки для уведомления", "h_every": "минут между проверками",
    "h_ntfy_topic": "топик ntfy (сложный, чтобы не угадали)", "h_ntfy_server": "адрес сервера ntfy",
    "h_email_to": "куда слать дайджест", "h_smtp_host": "SMTP-сервер", "h_smtp_port": "порт SMTP (587 / 465)",
    "h_smtp_user": "логин SMTP", "h_smtp_password": "пароль SMTP / пароль приложения (скрыт)",
    "h_discord_webhook": "URL вебхука Discord (скрыт)", "h_telegram_token": "токен Telegram-бота (скрыт)",
    "h_telegram_chat": "id чата Telegram (ставится настройкой сам)",
    "err_unknown_cmd": "нет команды «{cmd}»", "hint_help": "все команды: sift help",
    "ui_updating": "обновляю…", "ui_refresh_failed": "не удалось обновить, показаны сохранённые данные",
    "h_covers": "обложки в приложении: auto (настоящие картинки, где терминал умеет) | sixel | blocks | off",
    "ui_tab_picks": "Для тебя", "ui_tab_wish": "Вишлист", "ui_tab_hidden": "Скрытые", "ui_tab_taste": "Вкус",
    "ui_k_quit": "Выход", "ui_k_open": "Открыть", "ui_k_hide": "Скрыть", "ui_k_undo": "Вернуть", "ui_k_search": "Поиск",
    "ui_k_filters": "Фильтры", "ui_k_sort": "Сортировка", "ui_k_refresh": "Обновить", "ui_k_theme": "Тема",
    "ui_search_ph": "поиск по названию…", "ui_nothing": "С такими фильтрами здесь пусто.",
    "ui_hide_question": "Больше не рекомендовать — почему?", "ui_undo_hint": "u — вернуть",
    "ui_open": "открыть в магазине", "ui_filters": "фильтры",
    "ui_filters_hint": "только для этого экрана · постоянные: sift config",
    "ui_apply": "Применить", "ui_filters_off": "фильтры выключены", "ui_f_lowest": "★ только рекорды",
    "ui_f_budget": "в пределах бюджета", "ui_f_deck": "работает на Steam Deck", "ui_f_lang": "на моём языке",
    "ui_f_no_ea": "без раннего доступа", "ui_sorted": "сортировка: {by}", "ui_sort_score": "совпадение",
    "ui_sort_price": "цена", "ui_sort_cut": "скидка", "ui_sort_ends": "скоро закончится",
    "wz_back": "← Назад", "wz_next": "Далее →", "wz_checking": "проверяю…", "wz_optional": "необязательно",
    "wz_welcome": "sift находит скидки Steam под твой вкус — а не просто самые большие.\n"
                  "Настройка займёт около 3 минут. Ключи остаются на этом компьютере, в системном хранилище.\n\nЯзык:",
    "wz_key_title": "Ключ Steam Web API",
    "wz_key_help": "Он нужен, чтобы читать библиотеку и время в играх. Открой страницу, войди, впиши любой домен "
                   "(например localhost), согласись и скопируй ключ из 32 символов.",
    "wz_open_key_page": "Открыть страницу ключа ↗", "wz_key_ok": "ключ работает", "wz_key_len": "{n}/32 символов",
    "wz_profile_title": "Твой профиль Steam",
    "wz_profile_help": "Вставь ссылку на профиль, ник, SteamID или friend code — подойдёт что угодно.",
    "wz_is_you": "{name} — это ты", "wz_games_n": "игр: {n}", "wz_games_hidden": "игры скрыты",
    "wz_wishlist_n": "в вишлисте: {n}",
    "wz_privacy_title": "Проверка приватности", "wz_open_privacy": "Открыть настройки приватности ↗",
    "wz_recheck": "Проверить снова",
    "wz_pv_profile": "профиль открыт", "wz_pv_fix_profile": "Мой профиль: Открытый",
    "wz_pv_games": "игровые данные видны (игр: {n})", "wz_pv_fix_games": "Игровые данные: Открытые",
    "wz_pv_playtime": "время в играх видно", "wz_pv_fix_playtime": "сними галочку «Всегда скрывать общее время в игре»",
    "wz_pv_wishlist": "вишлист виден ({n})", "wz_pv_fix_wishlist": "необязательно",
    "wz_region_title": "Регион магазина",
    "wz_region_help": "Цены и доступность зависят от страны аккаунта Steam (не от IP). "
                      "Даже в долларах цены разные: MENA, CIS, LATAM, Южная Азия, США.",
    "wz_region_ip": "По IP это {name} ({code}). Аккаунт из другой страны? Найди её ниже.",
    "wz_region_search": "название страны или код…", "wz_region_example": "цены выглядят так: {price}",
    "wz_family_title": "Семья Steam", "wz_family_auto": "Игры, которыми семья может поделиться, исключаются сами.",
    "wz_family_none": "Семья в клиенте Steam не найдена — вставь ссылки участников ниже или пропусти.",
    "wz_family_manual": "Участники (необязательно, через пробел):",
    "wz_itad_title": "История цен (необязательно)",
    "wz_itad_help": "Бесплатный ключ IsThereAnyDeal добавит к каждой скидке «★ рекорд / было −90%». "
                    "Открой страницу, создай приложение, скопируй его API key.",
    "wz_open_itad": "Открыть IsThereAnyDeal ↗", "wz_itad_skip": "пропущено — можно добавить позже",
    "wz_prefs_title": "Предпочтения", "wz_pref_game_lang": "Игры на моём языке",
    "wz_any": "не важно", "wz_subs": "хотя бы субтитры", "wz_audio": "с озвучкой",
    "wz_pref_adult": "Скрывать игры 18+", "wz_pref_ea": "Скрывать ранний доступ",
    "wz_pref_third": "Скрывать игры с аккаунтами EA/Ubisoft/…", "wz_pref_budget": "Бюджет (в валюте магазина)",
    "wz_pref_min_discount": "Минимальная скидка, %",
    "wz_seeds_title": "Пара любимых игр", "wz_seeds_search": "введи игру и нажми Enter…",
    "wz_seeds_help": "История в Steam короткая — назови 3–5 любимых игр (с любой платформы).",
    "wz_notify_title": "Уведомления", "wz_notify_help": "Лучшие скидки сами придут к тебе — рекорды из вишлиста, "
                                                       "сильные находки, последние шансы. По умолчанию — раз в день.",
    "wz_ch_desktop": "Уведомления Windows", "wz_ch_later": "Позже",
    "wz_tg_step1": "Создай личного бота: открой @BotFather → /newbot → любое имя → вставь токен сюда.",
    "wz_open_botfather": "Открыть @BotFather ↗", "wz_tg_link": "Привязать бота",
    "wz_tg_press_start": "теперь нажми Start в @{bot} — Telegram уже открыт",
    "wz_done_title": "Готово", "wz_show": "Показать подборку", "wz_exit": "Выйти",
    "wz_done_hint": "Потом: sift · sift macro · sift doctor · sift notify enable · sift config help",
    "wz_sum_family": "семья: {v}", "wz_sum_itad": "история цен: {v}", "wz_sum_notify": "уведомления: {v}",
    "wz_sum_seeds": "любимых игр: {n}",
})

# --------------------------------------------------------------------------- discover · queries · macros
EN.update({
    "sec_discover": "discover · new for you", "ui_tab_discover": "Discover",
    "sp_discover": "looking beyond your usual genres…",
    "empty_discover": "Nothing new-for-you passes these filters — try fewer of them.",
    "why_new": "new for you: {tag}", "why_bridge": "from your taste: {tag}",
   
    "q_price": "≤ {p}", "q_any_price": "any price", "q_cut": "−{n}%+", "q_lowest": "★ record low",
    "q_near": "◆ near record", "q_no_tags": "no {tags}", "q_rating": "≥ {n}% positive",
    "q_reviews_between": "{a}–{b} reviews", "q_reviews_min": "≥ {n} reviews", "q_reviews_max": "≤ {n} reviews",
    "q_score": "score ≥ {n}", "q_since": "since {y}", "q_ending": "ends ≤ {n}d",
    "q_bad_cut": "discount must be 0–100", "q_unknown_flags": "unknown flags: {flags}",
    "q_bad_tag": "unknown tag “{tag}”", "q_shown": "{n} of {total}",
    "sec_macros": "macros", "m_col_name": "macro", "m_col_what": "shows", "m_col_flags": "flags",
    "m_builtin": "built-in", "m_saved": "macro saved — run it: sift {name}", "m_removed": "macro {name} removed",
    "m_unknown": "no macro “{name}”", "m_bad_name": "“{name}” can't be a macro name (letters, digits, - and _)",
    "m_reserved": "“{name}” is a sift command — pick another name",
    "m_builtin_rm": "{name} is built in — redefine it instead: sift macro add {name} <flags>",
    "m_need_flags": "what should it show? e.g. sift macro add {name} -b 2 -g indie --lowest",
    "m_hint": "new: sift macro add <name> <flags>  ·  e.g. sift macro add cheap -b 2 -g indie --lowest  ·  "
              "remove: sift macro rm <name>  ·  in the app: f",
    "m_all_defaults": "everything (defaults)",
    "ui_k_macros": "Macros", "ui_k_clear": "Clear", "ui_macros": "macros",
    "ui_macros_hint": "enter — apply", "ui_macro_applied": "macro {name}",
    "ui_save_macro": "Save as macro", "ui_macro_name_ph": "macro name, e.g. cheap", "ui_reset": "Reset",
    "ui_cleared": "filters cleared", "ui_f_near": "◆ at or near record lows", "ui_f_price": "max price",
    "ui_f_cut": "min discount %", "ui_f_rating": "min % positive", "ui_f_tags": "tags",
    "ui_f_no_tags": "without tags", "ui_f_bad": "check the fields: {err}",
    "ui_sort_rating": "rating", "ui_sort_new": "newest",
    "ui_filters_hint2": "this view only",
})

RU.update({
    "sec_discover": "открытия · новое для тебя", "ui_tab_discover": "Открытия",
    "sp_discover": "смотрю за пределами привычных жанров…",
    "empty_discover": "Ничего нового под эти фильтры — попробуй ослабить их.",
    "why_new": "новое: {tag}", "why_bridge": "из твоего: {tag}",
   
    "q_price": "≤ {p}", "q_any_price": "любая цена", "q_cut": "−{n}%+", "q_lowest": "★ рекорд",
    "q_near": "◆ около рекорда", "q_no_tags": "без: {tags}", "q_rating": "отзывы ≥ {n}%",
    "q_reviews_between": "{a}–{b} отзывов", "q_reviews_min": "≥ {n} отзывов", "q_reviews_max": "≤ {n} отзывов",
    "q_score": "оценка ≥ {n}", "q_since": "с {y} года", "q_ending": "скидка ≤ {n}д",
    "q_bad_cut": "скидка — от 0 до 100", "q_unknown_flags": "неизвестные флаги: {flags}",
    "q_bad_tag": "нет такого тега «{tag}»", "q_shown": "{n} из {total}",
    "sec_macros": "макросы", "m_col_name": "макрос", "m_col_what": "что показывает", "m_col_flags": "флаги",
    "m_builtin": "встроенный", "m_saved": "макрос сохранён — запуск: sift {name}",
    "m_removed": "макрос {name} удалён", "m_unknown": "нет макроса «{name}»",
    "m_bad_name": "«{name}» не годится для имени макроса (буквы, цифры, - и _)",
    "m_reserved": "«{name}» — это команда sift, выбери другое имя",
    "m_builtin_rm": "{name} встроенный — его можно переопределить: sift macro add {name} <флаги>",
    "m_need_flags": "что он должен показывать? например: sift macro add {name} -b 2 -g инди --lowest",
    "m_hint": "новый: sift macro add <имя> <флаги>  ·  например: sift macro add cheap -b 2 -g инди --lowest  ·  "
              "удалить: sift macro rm <имя>  ·  в приложении: f",
    "m_all_defaults": "всё (по умолчанию)",
    "ui_k_macros": "Макросы", "ui_k_clear": "Сброс", "ui_macros": "макросы",
    "ui_macros_hint": "enter — применить",
    "ui_macro_applied": "макрос {name}", "ui_save_macro": "Сохранить как макрос",
    "ui_macro_name_ph": "имя макроса, например cheap", "ui_reset": "Сбросить", "ui_cleared": "фильтры сброшены",
    "ui_f_near": "◆ рекорд или около него", "ui_f_price": "цена до", "ui_f_cut": "скидка от, %",
    "ui_f_rating": "отзывы от, %", "ui_f_tags": "теги", "ui_f_no_tags": "без тегов",
    "ui_f_bad": "проверь поля: {err}", "ui_sort_rating": "отзывы", "ui_sort_new": "новинки",
    "ui_filters_hint2": "только этот экран",
})

# --------------------------------------------------------------------------- deal intelligence · cadence · bundles · keyboard UX
EN.update({
    "v_2y_low": "◆ 2Y low (was −{n}%)",
    "cad_rare_year": "rare sale · once a year",
    "cad_rare_months": "rare sale · every {m} mo",
    "cad_occasional_months": "sale every {m} mo",
    "cad_frequent_weeks": "frequent · every {w} wk",
    "cad_since_days": "{d}d since last",
    "bnd_cts": "📦 Complete the Set",
    "bnd_cts_pct": "📦 Complete the Set −{pct}%",
    "bnd_owned_n": "{n} owned",
    "bnd_games_n": "📦 bundle · {n} games",
    "bnd_extra_pct": "📦 bundle −{pct}%",
    "bnd_package": "📦 bundle",
    "bnd_edition": "{ed} Edition",
    "q_low_2y": "◆ 2Y low",
    "q_rare": "◈ rare sale",
    "q_bundle": "📦 bundle",
    "ui_f_low_2y": "◆ 2-year lows (2YL)",
    "ui_f_rare": "◈ rare discounts only",
    "ui_f_bundle": "📦 bundles & sets",
    "ui_sort_deal": "deal value",
    "ui_sort_atl": "ATL / 2Y low",
    "ui_sort_rarity": "sale rarity",
    "ui_sort_taste": "taste match",
    "ui_k_help": "Help",
    "ui_k_bundle": "Bundle/ITAD",
    "ui_tab_picks": "Top deals",
    "ui_qf_atl": "★ ATL",
    "ui_qf_2y": "◆ 2Y low",
    "ui_qf_rare": "◈ Rare",
    "ui_qf_bundle": "📦 Bundles",
    "ui_actions_bar": "[b #10f587]enter/o[/] Steam  [b #00e5ff]b[/] ITAD/bundle  [b #ffb800]f[/] filters  [b #ff3b6b]x[/] hide",
    "ui_help_title": "keyboard shortcuts",
    "ui_help_body": (
        "[b]Navigation[/]\n"
        "  ↑/↓ or j/k       move between rows\n"
        "  g / G            jump to first / last row\n"
        "  PgUp / PgDn      scroll page up / down\n"
        "  ←/→ or [ / ]     previous / next tab\n"
        "  1–6              jump directly to tab 1–6\n\n"
        "[b]One-Key Deal Toggles (Instant)[/]\n"
        "  a                toggle ★ All-Time Low (ATL) only\n"
        "  y                toggle ◆ 2-Year Low (2YL) only\n"
        "  w                toggle ◈ Rare sales only\n"
        "  p                toggle 📦 Bundles & Complete-the-Set\n\n"
        "[b]Deal Actions[/]\n"
        "  Enter or o       open game in Steam Store\n"
        "  b                open bundle or ITAD price history\n"
        "  x or h           hide deal (or restore in Hidden)\n"
        "  u                undo last hide / restore\n\n"
        "[b]Filtering & Sorting[/]\n"
        "  /                live search (Down/Enter → table, Esc → clear)\n"
        "  f                filter menu (↑/↓/←/→, 1–8 toggle, Enter apply)\n"
        "  m                presets & macros (1–9 apply, n new, d delete)\n"
        "  s / S            cycle sort forward / backward\n"
        "  c                clear all active filters\n"
        "  r                refresh live prices\n"
        "  Ctrl+T           toggle dark / light theme\n"
        "  q                quit"
    ),
    "deal_quality_lbl": "deal",
    "taste_match_lbl": "taste {pct}%",
    "opened_itad": "opened ITAD: {name}",
    "opened_bundle": "opened bundle: {name}",
})

RU.update({
    "v_2y_low": "◆ минимум за 2 года (было −{n}%)",
    "cad_rare_year": "редкая скидка · раз в год",
    "cad_rare_months": "редкая скидка · раз в {m} мес",
    "cad_occasional_months": "скидка раз в {m} мес",
    "cad_frequent_weeks": "частая · каждые {w} нед",
    "cad_since_days": "{d} дн. без скидки",
    "bnd_cts": "📦 Дополнить набор",
    "bnd_cts_pct": "📦 Дополнить набор −{pct}%",
    "bnd_owned_n": "{n} уже есть",
    "bnd_games_n": "📦 бандл · {n} игр",
    "bnd_extra_pct": "📦 бандл −{pct}%",
    "bnd_package": "📦 бандл",
    "bnd_edition": "издание {ed}",
    "q_low_2y": "◆ минимум 2 лет",
    "q_rare": "◈ редкая скидка",
    "q_bundle": "📦 бандл",
    "ui_f_low_2y": "◆ минимум за 2 года",
    "ui_f_rare": "◈ только редкие скидки",
    "ui_f_bundle": "📦 бандлы и наборы",
    "ui_sort_deal": "ценность скидки",
    "ui_sort_atl": "рекорд / 2 года",
    "ui_sort_rarity": "редкость скидки",
    "ui_sort_taste": "вкус",
    "ui_k_help": "Справка",
    "ui_k_bundle": "Бандл/ITAD",
    "ui_tab_picks": "Топ скидок",
    "ui_qf_atl": "★ ATL",
    "ui_qf_2y": "◆ 2Y Low",
    "ui_qf_rare": "◈ Редкие",
    "ui_qf_bundle": "📦 Бандлы",
    "ui_actions_bar": "[b #10f587]enter/o[/] в Steam  [b #00e5ff]b[/] ITAD/бандл  [b #ffb800]f[/] фильтры  [b #ff3b6b]x[/] скрыть",
    "ui_help_title": "управление с клавиатуры",
    "ui_help_body": (
        "[b]Навигация[/]\n"
        "  ↑/↓ или j/k      перемещение по списку\n"
        "  g / G            в начало / в конец списка\n"
        "  PgUp / PgDn      страница вверх / вниз\n"
        "  ←/→ или [ / ]    предыдущая / следующая вкладка\n"
        "  1–6              переход сразу на вкладку 1–6\n\n"
        "[b]Быстрые тумблеры сделок (в 1 клавишу)[/]\n"
        "  a                только ★ рекорды за всё время (ATL)\n"
        "  y                только ◆ минимумы за 2 года (2YL)\n"
        "  w                только ◈ редкие скидки\n"
        "  p                только 📦 бандлы и Complete-the-Set\n\n"
        "[b]Действия со скидкой[/]\n"
        "  Enter или o      открыть страницу в Steam\n"
        "  b                открыть бандл или историю цен ITAD\n"
        "  x или h          скрыть игру (или вернуть в Скрытых)\n"
        "  u                отменить скрытие / вернуть\n\n"
        "[b]Фильтры и сортировка[/]\n"
        "  /                быстрый поиск (↓/Enter → к списку, Esc → сброс)\n"
        "  f                меню фильтров (↑/↓/←/→, 1–8 чекбоксы, Enter применить)\n"
        "  m                пресеты и макросы (1–9 выбрать, n создать, d удалить)\n"
        "  s / S            сменить сортировку (вперёд / назад)\n"
        "  c                сбросить все фильтры\n"
        "  r                обновить цены\n"
        "  Ctrl+T           сменить тему (тёмная / светлая)\n"
        "  q                выход"
    ),
    "deal_quality_lbl": "выгода",
    "taste_match_lbl": "вкус {pct}%",
    "opened_itad": "открыт ITAD: {name}",
    "opened_bundle": "открыт бандл: {name}",
})

_TABLES = {"en": EN, "ru": RU}

_REVIEW_RU = {
    "Overwhelmingly Positive": "Крайне положительные", "Very Positive": "Очень положительные",
    "Positive": "Положительные", "Mostly Positive": "В основном положительные", "Mixed": "Смешанные",
    "Mostly Negative": "В основном отрицательные", "Negative": "Отрицательные",
    "Very Negative": "Очень отрицательные", "Overwhelmingly Negative": "Крайне отрицательные",
}


def review_label(label: str) -> str:
    return _REVIEW_RU.get(label, label) if lang() == "ru" else label


def lang() -> str:
    c = getattr(config, "cfg", None)
    return c.lang if c else "en"


def t(key: str, **kw) -> str:
    s = _TABLES.get(lang(), EN).get(key) or EN.get(key, key)
    return s.format(**kw) if kw else s


def num(n: int) -> str:
    """851931 -> '851,931' / '851 931'."""
    s = f"{n:,}"
    return s.replace(",", "\u202f") if lang() == "ru" else s


_MONTHS = {"en": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),
           "ru": "янв фев мар апр мая июн июл авг сен окт ноя дек".split()}


def day_month(d) -> str:
    """date -> '12 Apr' / '12 апр'."""
    return f"{d.day} {_MONTHS.get(lang(), _MONTHS['en'])[d.month - 1]}"


def date(ts: int) -> str:
    import time
    return time.strftime("%d.%m.%Y" if lang() == "ru" else "%d %b %Y", time.localtime(ts))


EN.update({
    "vd_hot": "HOT", "vd_great": "GREAT", "vd_ok": "OK", "vd_meh": "MEH", "vd_nope": "NOPE",
    "vr_cheaper_before": "it has been {n}% cheaper",
    "vr_rare_first": "its first discount in two years",
    "vr_returns": "record price, back every ~{n} days",
    "vr_atl_unknown": "Steam record low; how often it returns isn't known yet",
    "tu_ends_d": "sale ends in {n} days", "tu_ends_h": "sale ends in {n} h",
    "tu_first_sale": "its first discount", "tu_no_sales": "no discounts in 2 years",
    "vr_atl": "Steam record low", "vr_low_2y": "2-year low −{n}%",
    "vr_rare": "rare sale: {n} in 2 years", "vr_typical": "typical discount −{n}%",
    "vr_deeper_before": "was −{n}%", "vr_fake": "price raised {n} days ago",
    "vr_sale_soon": "sale in {n} days", "vr_bundle": "cheaper in a bundle",
})
RU.update({
    "vd_hot": "ОГОНЬ", "vd_great": "КЛАСС", "vd_ok": "НОРМ", "vd_meh": "ТАК СЕБЕ", "vd_nope": "МИМО",
    "vr_cheaper_before": "бывало на {n}% дешевле",
    "vr_rare_first": "первая скидка за два года",
    "vr_returns": "рекорд, но бывает каждые ~{n} дн.",
    "vr_atl_unknown": "рекорд Steam; как часто так бывает, пока неизвестно",
    "tu_ends_d": "скидка ещё {n} дн.", "tu_ends_h": "скидка ещё {n} ч",
    "tu_first_sale": "первая скидка у этой игры", "tu_no_sales": "за 2 года скидок не было",
    "vr_atl": "рекорд Steam", "vr_low_2y": "минимум за 2 года −{n}%",
    "vr_rare": "скидка редкая: {n} за 2 года", "vr_typical": "обычная скидка −{n}%",
    "vr_deeper_before": "бывало −{n}%", "vr_fake": "цену подняли {n} дн. назад",
    "vr_sale_soon": "распродажа через {n} дн.", "vr_bundle": "дешевле в наборе",
})


# --------------------------------------------------------------------------- the app (tui/app.py)
EN.update({
    "tu_tab_deals": "Deals", "tu_tab_wish": "Wishlist", "tu_tab_discover": "Discover", "tu_tab_dlc": "DLC",
    "tu_search_ph": "type to filter by title · enter or ↓ back to the list · esc clear",
    "tu_col_reviews": "rev.", "tu_sorted": "by {by}", "ui_sort_match": "taste match",
    "tu_k_open": "open", "tu_k_search": "search", "tu_k_filters": "filters", "tu_k_sort": "sort",
    "tu_k_hide": "hide", "tu_k_keys": "all keys", "tu_k_quit": "quit", "tu_k_details": "details",
    "tu_h_details": "show / hide the details pane (narrow windows)",
    "tu_sale_now": "{name} is on now", "tu_sale_next": "{name} in {n} days",
    "tu_empty": "Nothing on sale here right now.",
    "tu_empty_filtered": "Nothing matches these filters.  0 resets them, f changes them.",
    "tu_no_bundle": "No bundle for this game", "tu_dlc_for": "DLC for {name}",
    "tu_hidden_taste": "{name} hidden, it won't be suggested again · u undo",
    "tu_hidden_owned": "{name} hidden as already owned · u undo",
    "tu_sales_2y": "{n} sales in 2 years", "tu_usually": "usually −{n}%", "tu_best": "best −{n}%",
    "tu_since_last": "last sale ended {n} days ago",
    "tu_filters": "Filters", "tu_any": "any",
    "tu_filters_foot": "press a key or enter · changes apply at once · esc closes",
    "tu_f_show": "Show only", "tu_f_limits": "Limits", "tu_f_saved": "Saved filters",
    "tu_f_buy": "only HOT deals", "tu_f_lowest": "record lows", "tu_f_2y": "lowest in 2 years",
    "tu_f_rare": "rare sales", "tu_f_bundle": "bundles and sets", "tu_f_deck": "Steam Deck verified or playable",
    "tu_f_lang": "in my language", "tu_f_no_ea": "no early access",
    "tu_f_family": "games my Steam Family shares  ⌂", "h_family": "also list games your Steam Family shares: on | off",
    "tu_family_has": "⌂ already in your Steam Family ({owner})", "q_family": "⌂ with family games",
    "tu_f_price": "price up to", "tu_f_cut": "discount from", "tu_f_rating": "reviews from",
    "tu_f_tags": "with tags", "tu_f_no_tags": "without tags",
    "tu_f_save": "save these filters as…", "tu_f_save_ph": "name, then enter (e.g. cheap)",
    "tu_f_hidden": "hidden games", "tu_f_reset": "reset all filters",
    "tu_hidden_title": "Hidden games", "tu_hidden_foot": "enter or x brings a game back · esc closes",
    "tu_hidden_none": "You haven't hidden anything.",
    "tu_help_title": "Keys",
    "tu_h_move": "Move", "tu_h_rows": "previous / next game", "tu_h_ends": "first / last game",
    "tu_h_tabs": "switch tabs",
    "tu_h_game": "This game", "tu_h_open": "open in Steam", "tu_h_itad": "price history on IsThereAnyDeal",
    "tu_h_bundle": "open its bundle", "tu_h_hide": "hide: not for me", "tu_h_own": "hide: I own it elsewhere",
    "tu_h_undo": "undo the last hide",
    "tu_h_list": "The list", "tu_h_search": "search by title", "tu_h_filters": "filters, saved filters, hidden games",
    "tu_h_sort": "next / previous sort", "tu_h_reset": "reset filters", "tu_h_refresh": "refresh prices",
    "tu_h_app": "App", "tu_h_help": "this page", "tu_h_quit": "quit",
    "tu_help_verdicts": "Verdicts",
    "tu_v_hot": "a price that rarely comes back: grab it",
    "tu_v_great": "record price, but it returns every few weeks",
    "tu_v_ok": "an ordinary discount for this game",
    "tu_v_meh": "it has been a bit cheaper, or a big sale is near",
    "tu_v_nope": "it has been much cheaper, or the price was raised",
})
RU.update({
    "tu_tab_deals": "Скидки", "tu_tab_wish": "Вишлист", "tu_tab_discover": "Открытия", "tu_tab_dlc": "DLC",
    "tu_search_ph": "начни печатать название · enter или ↓ к списку · esc очистить",
    "tu_col_reviews": "отз.", "tu_sorted": "по: {by}", "ui_sort_match": "совпадению со вкусом",
    "tu_k_open": "открыть", "tu_k_search": "поиск", "tu_k_filters": "фильтры", "tu_k_sort": "сортировка",
    "tu_k_hide": "скрыть", "tu_k_keys": "все клавиши", "tu_k_quit": "выход", "tu_k_details": "детали",
    "tu_h_details": "показать / скрыть карточку игры (узкие окна)",
    "tu_sale_now": "идёт {name}", "tu_sale_next": "{name} через {n} дн.",
    "tu_empty": "Здесь сейчас нет скидок.",
    "tu_empty_filtered": "Под эти фильтры ничего не подходит.  0 сбросит их, f изменит.",
    "tu_no_bundle": "У этой игры нет набора", "tu_dlc_for": "DLC к {name}",
    "tu_hidden_taste": "{name} скрыта и больше не будет предлагаться · u вернуть",
    "tu_hidden_owned": "{name} скрыта как уже купленная · u вернуть",
    "tu_sales_2y": "{n} скидок за 2 года", "tu_usually": "обычно −{n}%", "tu_best": "рекорд −{n}%",
    "tu_since_last": "прошлая скидка кончилась {n} дн. назад",
    "tu_filters": "Фильтры", "tu_any": "любая",
    "tu_filters_foot": "нажми клавишу или enter · применяется сразу · esc закрыть",
    "tu_f_show": "Показывать только", "tu_f_limits": "Ограничения", "tu_f_saved": "Сохранённые фильтры",
    "tu_f_buy": "только ОГОНЬ", "tu_f_lowest": "рекордные цены", "tu_f_2y": "минимум за 2 года",
    "tu_f_rare": "редкие скидки", "tu_f_bundle": "наборы и комплекты", "tu_f_deck": "работает на Steam Deck",
    "tu_f_lang": "на моём языке", "tu_f_no_ea": "без раннего доступа",
    "tu_f_family": "игры из Семьи Steam  ⌂", "h_family": "показывать игры, которые есть в Семье Steam: on | off",
    "tu_family_has": "⌂ уже есть в Семье Steam ({owner})", "q_family": "⌂ с играми семьи",
    "tu_f_price": "цена до", "tu_f_cut": "скидка от", "tu_f_rating": "отзывы от",
    "tu_f_tags": "с тегами", "tu_f_no_tags": "без тегов",
    "tu_f_save": "сохранить эти фильтры как…", "tu_f_save_ph": "имя и enter (например cheap)",
    "tu_f_hidden": "скрытые игры", "tu_f_reset": "сбросить все фильтры",
    "tu_hidden_title": "Скрытые игры", "tu_hidden_foot": "enter или x вернёт игру · esc закрыть",
    "tu_hidden_none": "Ты ничего не скрывал.",
    "tu_help_title": "Клавиши",
    "tu_h_move": "Движение", "tu_h_rows": "предыдущая / следующая игра", "tu_h_ends": "первая / последняя игра",
    "tu_h_tabs": "вкладки",
    "tu_h_game": "Эта игра", "tu_h_open": "открыть в Steam", "tu_h_itad": "история цен на IsThereAnyDeal",
    "tu_h_bundle": "открыть её набор", "tu_h_hide": "скрыть: не моё", "tu_h_own": "скрыть: уже есть в другом месте",
    "tu_h_undo": "вернуть последнюю скрытую",
    "tu_h_list": "Список", "tu_h_search": "поиск по названию", "tu_h_filters": "фильтры, сохранённые, скрытые",
    "tu_h_sort": "следующая / предыдущая сортировка", "tu_h_reset": "сбросить фильтры", "tu_h_refresh": "обновить цены",
    "tu_h_app": "Программа", "tu_h_help": "эта страница", "tu_h_quit": "выход",
    "tu_help_verdicts": "Вердикты",
    "tu_v_hot": "такая цена бывает редко: хватай",
    "tu_v_great": "рекордная цена, но бывает каждый месяц-два",
    "tu_v_ok": "обычная скидка для этой игры",
    "tu_v_meh": "бывало немного дешевле, или близко распродажа",
    "tu_v_nope": "бывало намного дешевле, или цену подняли",
})


# --------------------------------------------------------------------------- setup wizard, second pass
EN.update({
    "wz_welcome": "sift checks every Steam discount against two years of prices and tells you which ones are "
                  "worth it: HOT, GREAT, OK, MEH or NOPE.",
    "wz_need": "Setup takes about 3 minutes. You will need:\n"
               "  [b]1[/]  a Steam Web API key            [dim]free · about 1 min · needs Steam Guard[/]\n"
               "  [b]2[/]  an IsThereAnyDeal API key      [dim]free · about 1 min · for the price history[/]\n"
               "  [b]3[/]  your Steam profile, store region and Steam Family\n"
               "     [dim]sift can find these on this computer, or you type them in[/]",
    "wz_scan_ask": "May sift look on this computer for your Steam account and Steam Family?\n"
                   "[dim]It reads only Steam's own files (loginusers.vdf, localconfig.vdf). Nothing is sent anywhere.[/]",
    "wz_scan_yes": "Yes, look on this PC", "wz_scan_no": "No, I'll type it myself",
    "wz_scan_running": "looking…",
    "wz_found_steam": "Steam installed in {path}", "wz_found_no_steam": "Steam isn't installed here: you'll paste your profile",
    "wz_found_account": "signed in as [b]{name}[/]  [dim]{sid}[/]", "wz_found_more": "[dim](+{n} more account on this PC)[/]",
    "wz_found_no_account": "no Steam account signed in here: you'll paste your profile link",
    "wz_found_family": "Steam Family “{name}”, {n} other member(s)", "wz_found_no_family": "no Steam Family on this PC",
    "wz_found_key": "a Steam API key is already saved", "wz_found_no_key": "the Steam API key is the next step",
    "wz_found_itad": "an IsThereAnyDeal key is already saved",
    "wz_scan_next": "Press [b]Next[/]: steps that were found are filled in for you.",
    "wz_key_title": "1 · Steam Web API key",
    "wz_key_steps": "It lets sift read your library and playtime. Takes a minute:\n"
                    "  [b]1[/]  open [u]{url}[/] and sign in\n"
                    "  [b]2[/]  Domain Name: type [b]localhost[/], tick the box, press Register\n"
                    "  [b]3[/]  confirm in the Steam mobile app (☰ menu → Confirmations)\n"
                    "  [b]4[/]  copy the Key: 32 letters and digits\n"
                    "[dim]Steam gives keys only to accounts that have spent at least $5 and use Steam Guard Mobile.[/]",
    "wz_itad_title": "2 · IsThereAnyDeal API key",
    "wz_itad_steps": "Two years of Steam price history: without it there are no HOT / GREAT / NOPE verdicts.\n"
                     "  [b]1[/]  open [u]{url}[/] and sign in (through Steam is quickest)\n"
                     "  [b]2[/]  press Register app, name it [b]sift[/], save\n"
                     "  [b]3[/]  copy the API Key: 40 letters and digits\n"
                     "[dim]Optional: leave the box empty to skip, add it later with  sift config set itad-key …[/]",
    "wz_clip_watch": "Copy the key and sift picks it up from the clipboard, or paste it below.",
    "wz_clip_got": "Key taken from the clipboard",
    "wz_s_welcome": "Welcome", "wz_s_key": "Steam key", "wz_s_itad": "Price history", "wz_s_profile": "Profile",
    "wz_s_privacy": "Privacy", "wz_s_region": "Store region", "wz_s_family": "Steam Family", "wz_s_prefs": "Filters",
    "wz_s_seeds": "Favourite games", "wz_s_notify": "Alerts", "wz_s_done": "Done",
})
RU.update({
    "wz_welcome": "sift сверяет каждую скидку Steam с ценами за два года и говорит, какие из них того стоят: "
                  "ОГОНЬ, КЛАСС, НОРМ, ТАК СЕБЕ или МИМО.",
    "wz_need": "Настройка займёт около 3 минут. Понадобится:\n"
               "  [b]1[/]  ключ Steam Web API              [dim]бесплатно · около минуты · нужен Steam Guard[/]\n"
               "  [b]2[/]  ключ IsThereAnyDeal API         [dim]бесплатно · около минуты · для истории цен[/]\n"
               "  [b]3[/]  твой профиль Steam, регион магазина и Семья Steam\n"
               "     [dim]sift может найти их на этом компьютере, или впишешь сам[/]",
    "wz_scan_ask": "Можно sift поискать на этом компьютере твой аккаунт Steam и Семью Steam?\n"
                   "[dim]Читаются только файлы самого Steam (loginusers.vdf, localconfig.vdf). Ничего никуда не отправляется.[/]",
    "wz_scan_yes": "Да, поищи на этом ПК", "wz_scan_no": "Нет, впишу сам",
    "wz_scan_running": "ищу…",
    "wz_found_steam": "Steam установлен в {path}", "wz_found_no_steam": "Steam здесь не установлен: вставишь ссылку на профиль",
    "wz_found_account": "вход выполнен как [b]{name}[/]  [dim]{sid}[/]", "wz_found_more": "[dim](+{n} ещё аккаунт на этом ПК)[/]",
    "wz_found_no_account": "в Steam здесь никто не входил: вставишь ссылку на профиль",
    "wz_found_family": "Семья Steam «{name}», других участников: {n}", "wz_found_no_family": "Семьи Steam на этом ПК нет",
    "wz_found_key": "ключ Steam API уже сохранён", "wz_found_no_key": "ключ Steam API — следующий шаг",
    "wz_found_itad": "ключ IsThereAnyDeal уже сохранён",
    "wz_scan_next": "Жми [b]Дальше[/]: найденное уже заполнено.",
    "wz_key_title": "1 · Ключ Steam Web API",
    "wz_key_steps": "Он нужен, чтобы читать библиотеку и время в играх. Это минута:\n"
                    "  [b]1[/]  открой [u]{url}[/] и войди\n"
                    "  [b]2[/]  Domain Name: впиши [b]localhost[/], отметь галочку, нажми Register\n"
                    "  [b]3[/]  подтверди в мобильном приложении Steam (меню ☰ → Подтверждения)\n"
                    "  [b]4[/]  скопируй Key: 32 буквы и цифры\n"
                    "[dim]Steam выдаёт ключ только аккаунтам, потратившим от $5 и с мобильным Steam Guard.[/]",
    "wz_itad_title": "2 · Ключ IsThereAnyDeal API",
    "wz_itad_steps": "История цен Steam за два года: без неё не будет вердиктов ОГОНЬ / КЛАСС / МИМО.\n"
                     "  [b]1[/]  открой [u]{url}[/] и войди (быстрее через Steam)\n"
                     "  [b]2[/]  нажми Register app, назови [b]sift[/], сохрани\n"
                     "  [b]3[/]  скопируй API Key: 40 букв и цифр\n"
                     "[dim]Можно пропустить, оставив поле пустым, и добавить позже: sift config set itad-key …[/]",
    "wz_clip_watch": "Скопируй ключ, и sift сам возьмёт его из буфера обмена, или вставь ниже.",
    "wz_clip_got": "Ключ взят из буфера обмена",
    "wz_s_welcome": "Начало", "wz_s_key": "Ключ Steam", "wz_s_itad": "История цен", "wz_s_profile": "Профиль",
    "wz_s_privacy": "Приватность", "wz_s_region": "Регион магазина", "wz_s_family": "Семья Steam", "wz_s_prefs": "Фильтры",
    "wz_s_seeds": "Любимые игры", "wz_s_notify": "Уведомления", "wz_s_done": "Готово",
})

# --------------------------------------------------------------------------- release wording
EN.update({
    "hint_setup": "Easiest: run  sift setup  (about 3 minutes). Or by hand:",
    "dr_itad_optional": "not set: optional, adds the price history behind HOT / GREAT / NOPE",
    "ev_wish_lowest": "Wishlist: a HOT price",
})
RU.update({
    "hint_setup": "Проще всего: запусти  sift setup  (около 3 минут). Или вручную:",
    "dr_itad_optional": "не задан: необязательно, даёт историю цен для вердиктов ОГОНЬ / КЛАСС / МИМО",
    "ev_wish_lowest": "Вишлист: цена ОГОНЬ",
})
