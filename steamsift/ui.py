"""Rendering. Minimal, single-line rows, clickable titles (OSC-8 hyperlinks), RU/EN."""
from __future__ import annotations

import sys
import time

from rich import box
from rich.cells import cell_len
from rich.console import Console
from rich.padding import Padding
from rich.style import Style
from rich.table import Table
from rich.text import Text

from . import config, region
from .i18n import date, day_month, num, review_label, t
from .presentation import cadence_badge, verdict_display as verdict, verdict_parts
from .recommender import META_TAGS, Profile, Rec, short_name
from .steam import Item, Library, local_tag

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

console = Console(legacy_windows=False, highlight=False)

ACCENT = "#66c0f4"   # Steam blue
HIDE_ICON = "⊘"      # "don't recommend"
MUTED = "grey50"
SEP = Text("  ·  ", style="grey35")


def _score_style(score: float) -> str:
    if score >= 80:
        return "bold bright_green"
    if score >= 65:
        return "green"
    if score >= 50:
        return "yellow"
    return MUTED


def score_cell(score: float) -> Text:
    filled = max(0, min(5, round(score / 20)))
    out = Text()
    out.append(f"{score:>3.0f} ", style=_score_style(score))
    out.append("▰" * filled, style=_score_style(score))
    out.append("▱" * (5 - filled), style="grey30")
    return out


def cut_cell(cut: int) -> Text:
    style = "bold bright_green" if cut >= 75 else "green" if cut >= 50 else "yellow"
    return Text(f"−{cut}%", style=style)


def ends_cell(ts: int) -> Text:
    if not ts:
        return Text("")
    secs = ts - time.time()
    if secs <= 0:
        return Text("")
    if secs < 86400:
        return Text(t("hours_short", n=f"{secs / 3600:.0f}"), style="bold red")
    days = secs / 86400
    return Text(t("days_short", n=f"{days:.0f}"), style="yellow" if days < 3 else MUTED)


def review_cell(item: Item) -> Text:
    pct = item.review_pct
    if pct is None or item.review_count < 10:
        return Text("—", style="grey30")
    style = "bright_green" if pct >= 90 else "green" if pct >= 80 else "yellow" if pct >= 70 else "red"
    return Text(f"{pct}%", style=style)


def game_cell(item: Item, width: int = 34, note: str = "") -> Text:
    out = Text(short_name(item.name, width), style=Style(bold=True, link=item.url))
    if item.early_access:
        out.append(" ea", style="grey42")
    if note:
        out.append(f"  {note}", style="grey42")
    return out


def price_text(item: Item) -> str:
    if item.final_fmt:
        return item.final_fmt
    return region.price_format(config.cfg.country).format(item.final_cents)


def money(value: float) -> str:
    """A user amount (budget) in the store's local format: $15.00, 1 500,00₸, ¥2,000."""
    return region.price_format(config.cfg.country).amount(value)


# --------------------------------------------------------------------------- header

def header(lib: Library, profile: Profile, hidden_count: int, itad_on: bool, family_count: int | None = None) -> None:
    c = config.cfg
    console.print()
    line = Text("  ")
    line.append("sift", style=f"bold {ACCENT}")
    line.append_text(SEP)
    line.append(lib.user_name, style="bold")
    line.append_text(SEP)
    line.append(region.label(c.country, c.lang), style=MUTED)
    if c.profile_name != "main":
        line.append_text(SEP)
        line.append(f"@{c.profile_name}", style="magenta")
    if c.budget:
        line.append_text(SEP)
        line.append(f"{t('budget')} ≤ {money(c.budget)}", style="green")
    if not itad_on:
        line.append_text(SEP)
        line.append(t("no_itad"), style="yellow")
    console.print(line)

    stats = Text("  ")
    parts = [(str(len(lib.my_games)), t("owned"))]
    fam = len(lib.family_games) if family_count is None else family_count
    if fam:
        parts.append((f"+{fam}", t("family")))
    parts.append((str(len(lib.wishlist)), t("wishlist")))
    if hidden_count:
        parts.append((f"{HIDE_ICON} {hidden_count}", t("hidden")))
    for i, (n, label) in enumerate(parts):
        if i:
            stats.append("   ")
        stats.append(n, style="bold")
        stats.append(f" {label}", style=MUTED)
    console.print(stats)

    top = profile.top_tags(6)
    if not top:
        return
    dna_line = Text(f"  {t('taste')}  ", style=MUTED)
    for i, (tag, _) in enumerate(top):
        if i:
            dna_line.append(" · ", style="grey35")
        dna_line.append(local_tag(tag).lower(), style=ACCENT)
    console.print(dna_line)


def section(title: str, icon: str, shown: int = 0, total: int = 0) -> None:
    console.print()
    line = Text(f"  {icon} ", style=ACCENT)
    line.append(title.upper(), style="bold")
    if total:
        line.append(f"   {shown} / {total}" if total > shown else f"   {total}", style=MUTED)
    console.print(line)


def _table() -> Table:
    return Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False, padding=(0, 1),
                 header_style=MUTED, border_style="grey23", expand=False)


# Column spec: (key, header, kind, width, options). "fixed" uses width (at least the header's),
# "flex" takes (min, max, share) of what's left. Columns with "drop" vanish (lowest first) when narrow.

def _layout(specs: list[tuple], indent: int = 3) -> list[tuple]:
    specs = [(k, h, kind, max(w, cell_len(h)) if kind == "fixed" else w, o) for k, h, kind, w, o in specs]
    avail = console.width - indent
    while True:
        fixed = sum(w for _, _, kind, w, _ in specs if kind == "fixed")
        flex = [sp for sp in specs if sp[2] == "flex"]
        pad = 3 * (len(specs) - 1)  # padding (0,1) + SIMPLE_HEAD divider between columns
        room = avail - fixed - pad
        if room >= sum(sp[3][0] for sp in flex):
            break
        droppable = [sp for sp in specs if sp[4].get("drop")]
        if not droppable:
            break
        specs.remove(min(droppable, key=lambda sp: sp[4]["drop"]))
    widths = {sp[0]: sp[3][0] for sp in flex}
    spare = max(0, room - sum(widths.values()))
    growable = [sp for sp in flex if widths[sp[0]] < sp[3][1]]
    while spare > 0 and growable:
        total_share = sum(sp[3][2] for sp in growable)
        given = 0
        for sp in growable:
            add = min(sp[3][1] - widths[sp[0]], max(1, spare * sp[3][2] // total_share), spare - given)
            widths[sp[0]] += add
            given += add
        spare -= given
        growable = [sp for sp in growable if widths[sp[0]] < sp[3][1]]
        if given == 0:
            break
    return [(k, h, widths.get(k, w), o) for k, h, kind, w, o in specs]


def _render(specs: list[tuple], rows: list[dict]) -> None:
    table = _table()
    cols = _layout(specs)
    for _, head, w, opts in cols:
        table.add_column(head, width=w, no_wrap=True, overflow="ellipsis",
                         justify=opts.get("justify", "left"), style=opts.get("style"))
    for row in rows:
        table.add_row(*(row.get(k, "") for k, _, _, _ in cols))
    console.print(Padding(table, (0, 0, 0, 1), expand=False))


# --------------------------------------------------------------------------- deal tables

def rec_table(recs: list[Rec], start: int = 1, show_history: bool = True) -> None:
    specs = [
        ("#", "#", "fixed", len(str(start + len(recs))), {"justify": "right", "style": "grey42"}),
        ("score", t("col_score"), "fixed", 9, {}),
        ("game", t("col_game"), "flex", (16, 40, 5), {}),
        ("price", t("col_price"), "fixed", max([cell_len(price_text(r.item)) for r in recs] + [6]),
         {"justify": "right", "style": "bold"}),
        ("cut", t("col_cut"), "fixed", 4, {"justify": "right"}),
    ]
    if show_history:
        specs.append(("history", t("col_verdict"), "fixed", 9, {"drop": 3}))
    specs += [
        ("ends", t("col_ends"), "fixed", 4, {"justify": "right", "drop": 2}),
        ("rev", t("col_rev"), "fixed", 4, {"justify": "right", "drop": 1}),
        ("why", t("col_why"), "flex", (14, 50, 5), {"style": "grey62", "drop": 4}),
    ]
    from .notify.cards import notes_for
    rows = []
    for i, r in enumerate(recs, start=start):
        label, style, reason = verdict_parts(r.item.cut, r.hist, r.verdict)
        hist = Text(label or "·", style=style or "grey35")
        notes = notes_for(r, wait=False)
        why = Text()
        if reason:
            why.append(reason, style="grey85")
            if notes or r.why:
                why.append(" · ", style="grey35")
        if notes:
            why.append(notes, style="bold yellow" if r.extras.get("target", {}).get("hit") else "yellow")
            if r.why:
                why.append(" · ", style="grey35")
        why.append(r.why, style="grey62")
        rows.append({
            "#": Text(str(i)), "score": score_cell(r.score), "game": game_cell(r.item, width=40, note=r.note),
            "price": price_text(r.item), "cut": cut_cell(r.item.cut), "history": hist,
            "ends": ends_cell(r.item.ends_at), "rev": review_cell(r.item), "why": why,
        })
    _render(specs, rows)


def calendar_lines(digest) -> list[Text]:
    """🔥 sale running · ⏳ next big sale soon · 🏁 fests that match your taste."""
    from .notify.cards import sale_name
    import datetime as dt
    today = dt.date.today()
    out = []
    if digest.sale_now:
        s = digest.sale_now
        out.append(Text(f"  🔥 {t('cal_running', sale=sale_name(s.name), end=day_month(s.end))}", style="bold #ff8a3d"))
    elif digest.sale_next:
        s = digest.sale_next
        out.append(Text(f"  ⏳ {t('cal_next', sale=sale_name(s.name), days=(s.start - today).days, start=day_month(s.start), end=day_month(s.end))}",
                        style="yellow"))
    for f in digest.fests[:2]:
        when = t("cal_now") if f.start <= today else f"{day_month(f.start)}–{day_month(f.end)}"
        out.append(Text(f"  🏁 {t('cal_fest', name=f.name, when=when)}", style=ACCENT))
    return out


def dlc_table(rows: list[dict], show_history: bool = True) -> None:
    specs = [
        ("#", "#", "fixed", len(str(len(rows))), {"justify": "right", "style": "grey42"}),
        ("dlc", t("col_dlc"), "flex", (16, 46, 6), {}),
        ("for", t("col_for"), "flex", (10, 28, 3), {"style": ACCENT, "drop": 4}),
        ("price", t("col_price"), "fixed", max([cell_len(price_text(r["item"])) for r in rows] + [6]),
         {"justify": "right", "style": "bold"}),
        ("cut", t("col_cut"), "fixed", 4, {"justify": "right"}),
    ]
    if show_history:
        specs.append(("history", t("col_verdict"), "fixed", 9, {"drop": 3}))
    specs += [
        ("ends", t("col_ends"), "fixed", 4, {"justify": "right", "drop": 2}),
        ("rev", t("col_rev"), "fixed", 4, {"justify": "right", "drop": 1}),
        ("owner", t("col_owner"), "flex", (10, 22, 2), {"style": "grey62", "drop": 5}),
    ]
    out = []
    for i, r in enumerate(rows, start=1):
        item: Item = r["item"]
        label, style, _ = verdict_parts(item.cut, r.get("hist"))
        out.append({
            "#": Text(str(i)), "dlc": game_cell(item, width=46), "for": short_name(r["base_name"], 28),
            "price": price_text(item), "cut": cut_cell(item.cut), "history": Text(label or "·", style=style or "grey35"),
            "ends": ends_cell(item.ends_at), "rev": review_cell(item), "owner": r["owner"],
        })
    _render(specs, out)


def footer(*extra: str) -> None:
    for e in extra:
        if e:
            console.print(Text(f"  {e}", style="grey42"))
    line = Text("  ")
    line.append(t("hint_click"), style="grey42")
    for hint in (t("hint_open"), t("hint_info")):
        line.append("  ·  ", style="grey30")
        line.append(hint, style="grey50")
    line.append("  ·  ", style="grey30")
    line.append(f"{HIDE_ICON} ", style="red")
    line.append(t("hint_hide"), style="grey50")
    console.print(line)
    console.print()


def empty(msg: str) -> None:
    console.print(Text(f"    {msg}", style=MUTED))


def error(msg: str) -> None:
    console.print(Text(f"  ✗ {msg}", style="bold red"))


def warn(msg: str) -> None:
    console.print(Text(f"  ! {msg}", style="yellow"))


def ok(msg: str) -> None:
    console.print(Text(f"  ✓ {msg}", style="green"))


def plain(msg: str, style: str = MUTED) -> None:
    console.print(Text(msg, style=style))


# --------------------------------------------------------------------------- other views

def dna(profile: Profile, lib: Library) -> None:
    section(t("sec_dna"), "◆")
    tags = profile.top_tags(15)
    top = tags[0][1] if tags else 1
    table = _table()
    table.add_column("#", justify="right", style="grey42", no_wrap=True)
    table.add_column(t("col_tag"), style="bold", no_wrap=True)
    table.add_column(t("col_share"), justify="right", style=MUTED)
    table.add_column("", no_wrap=True)
    for i, (tag, share) in enumerate(tags, 1):
        n = round(24 * share / top)
        table.add_row(str(i), local_tag(tag), f"{share * 100:.1f}%",
                      Text("━" * n, style=ACCENT) + Text("─" * (24 - n), style="grey23"))
    console.print(Padding(table, (0, 0, 0, 1), expand=False))

    section(t("sec_built"), "◆")
    sig = sorted((s for s in profile.signals if s.kind != "wishlist"), key=lambda s: -abs(s.weight))[:12]
    table = _table()
    table.add_column(t("col_game"), style="bold", no_wrap=True, max_width=36)
    table.add_column(t("col_signal"), style=MUTED)
    table.add_column(t("col_hours"), justify="right", style=MUTED)
    table.add_column(t("col_weight"), justify="right")
    for s in sig:
        style = "red" if s.weight < 0 else ACCENT
        table.add_row(short_name(s.name, 36), s.kind, f"{s.hours:.0f}" if s.hours else "",
                      Text(f"{s.weight:+.2f}", style=style))
    console.print(Padding(table, (0, 0, 0, 1), expand=False))
    if not lib.playtime_visible and lib.games_visible:
        warn(t("dna_no_playtime"))
    wish = sum(1 for s in profile.signals if s.kind == "wishlist")
    plain("  " + t("dna_note", n=wish), "grey42")
    console.print()


def family(lib: Library, unshared: int) -> None:
    section(t("sec_family", name=lib.family_name), "◆")
    if not lib.family_members:
        empty(t("empty_family"))
        console.print()
        return
    table = _table()
    table.add_column(t("col_member"), style="bold")
    table.add_column(t("col_games"), justify="right")
    table.add_column("", style=MUTED)
    for m in lib.family_members:
        table.add_row(m["name"], str(m["games_count"]) if m["games_count"] else t("family_private"),
                      t("you") if m["is_me"] else "")
    console.print(Padding(table, (0, 0, 0, 1), expand=False))
    src = t("family_src_manual") if lib.family_source == "manual" else t("family_src_client")
    plain(f"  {t('family_note', n=len(lib.family_games) - unshared)}  ({src})", "grey42")
    if unshared:
        plain("  " + t("family_unshared", n=unshared), "grey42")
    console.print()


def hidden_ok(name: str, why: str) -> None:
    line = Text("  ")
    line.append(f"{HIDE_ICON} ", style="bold red")
    line.append(short_name(name, 40), style="bold")
    line.append(f"  {t('hidden_ok')} · {why}", style=MUTED)
    console.print(line)


def hidden_list(hidden: dict[int, dict]) -> None:
    section(t("sec_hidden"), HIDE_ICON, len(hidden), len(hidden))
    if not hidden:
        empty(t("empty_hidden"))
        console.print()
        return
    table = _table()
    table.add_column("#", justify="right", style="grey42", no_wrap=True)
    table.add_column(t("col_game"), style="bold", no_wrap=True, overflow="ellipsis", max_width=44)
    table.add_column(t("col_reason"), style=MUTED, no_wrap=True)
    table.add_column(t("col_since"), style=MUTED, no_wrap=True)
    for i, (appid, h) in enumerate(hidden.items(), 1):
        name = Text(short_name(h["name"], 44), style=Style(bold=True, link=f"https://store.steampowered.com/app/{appid}/"))
        reason = t("reason_taste") if h.get("reason") == "taste" else t("reason_owned")
        table.add_row(str(i), name, reason, date(h.get("at", 0)))
    console.print(Padding(table, (0, 0, 0, 1), expand=False))
    plain("  " + t("restore_hint"), "grey42")
    console.print()


def info(rec: Rec, status: str) -> None:
    item = rec.item
    console.print()
    line = Text("  ")
    line.append(item.name, style=Style(bold=True, link=item.url))
    if status:
        line.append(f"   {status}", style="bold magenta")
    console.print(line)
    bits = []
    if item.developers:
        bits.append(", ".join(item.developers[:2]))
    if item.release:
        bits.append(time.strftime("%Y", time.localtime(item.release)))
    if item.review_count:
        bits.append(f"{review_label(item.review_label)} · {t('reviews_of', pct=item.review_pct, n=num(item.review_count))}")
    plain("  " + "  ·  ".join(bits))
    console.print()

    p = Text("  ")
    if not item.available:
        p.append(t("st_unavailable", country=region.name(config.cfg.country, config.cfg.lang)), style="bold red")
    elif item.is_free:
        p.append(t("free"), style="bold green")
    elif item.purchasable and item.final_cents:
        p.append(price_text(item), style="bold")
        if item.cut:
            p.append(f"  {item.orig_fmt}", style="strike grey50")
            p.append("  ")
            p.append_text(cut_cell(item.cut))
            e = ends_cell(item.ends_at)
            if e.plain:
                p.append(f"  {t('ends_in')} ", style=MUTED)
                p.append_text(e)
    else:
        p.append(t("not_purchasable"), style=MUTED)
    console.print(p)

    if rec.hist and item.available:
        label, style = verdict(item.cut, rec.hist, rec.verdict)
        h = Text(f"  {t('history'):<9}", style=MUTED)
        h.append(t("deepest", n=rec.hist.best_cut), style="bold")
        if label:
            h.append("   ")
            h.append(label, style=style)
        elif not item.cut:
            h.append(f"   {t('wait')}", style="yellow")
        cad = cadence_badge(rec.hist)
        if cad:
            h.append(f"   ·  ◈ {cad}", style="cyan" if rec.hist.tier == "rare" else MUTED)
        console.print(h)

    bnd = rec.extras.get("bundle") or ({"badge": item.bundle_badge()} if item.bundle_badge() else None)
    if bnd and bnd.get("badge"):
        plain(f"  {'bundle':<9}{bnd['badge']}", "cyan")

    m = Text(f"  {t('match'):<9}", style=MUTED)
    m.append_text(score_cell(rec.score))
    m.append(f"   {t('deal_quality_lbl')} {rec.deal_score:.0f} · {t('affinity')} {rec.affinity * 100:.0f}% · {t('quality')} {rec.quality * 100:.0f}%", style=MUTED)
    console.print(m)
    if rec.why:
        plain(f"  {t('why'):<9}{rec.why}", "grey62")
    if item.tags:
        tags = sorted(((k, w) for k, w in item.tags.items() if k not in META_TAGS), key=lambda kv: -kv[1])[:8]
        plain(f"  {t('tags'):<9}" + " · ".join(local_tag(x).lower() for x, _ in tags), "grey42")
    console.print()


# --------------------------------------------------------------------------- settings views

def kv_table(rows: list[tuple[str, str | Text]], title: str, icon: str = "◆") -> None:
    section(title, icon)
    table = Table(box=None, show_header=False, padding=(0, 2), pad_edge=False)
    table.add_column(style=MUTED, no_wrap=True)
    table.add_column()
    for k, v in rows:
        table.add_row(k, v)
    console.print(Padding(table, (0, 0, 0, 2), expand=False))


def simple_table(cols: list[str], rows: list[list], title: str, icon: str = "◆", total: int = 0) -> None:
    section(title, icon, len(rows), total or len(rows))
    table = _table()
    for c in cols:
        table.add_column(c, no_wrap=True)
    for r in rows:
        table.add_row(*r)
    console.print(Padding(table, (0, 0, 0, 1), expand=False))
