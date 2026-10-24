"""A channel-neutral, JSON-serialisable game card + renderers for each channel."""
from __future__ import annotations

import html
import time
from dataclasses import asdict, dataclass

from ..i18n import num, t
from ..recommender import Rec, short_name, verdict
from ..presentation import cadence_badge, verdict_text

# event kind -> (icon, i18n key of the headline)
KINDS = {
    "wish_target": ("🎯", "ev_wish_target"),
    "wish_lowest": ("★", "ev_wish_lowest"),
    "ending": ("⏰", "ev_ending"),
    "pick_strong": ("✦", "ev_pick_strong"),
    "dlc_lowest": ("✚", "ev_dlc_lowest"),
    "sale_start": ("🔥", "ev_sale_start"),
    "top": ("✦", "ev_top"),
}
COLORS = {"wish_target": 0xF5C542, "wish_lowest": 0x66C0F4, "ending": 0xE5534B, "pick_strong": 0x7CDB8A,
          "dlc_lowest": 0xB48EF0, "sale_start": 0xFF8A3D, "top": 0x66C0F4}


@dataclass
class Card:
    appid: int
    kind: str
    title: str
    price: str
    orig: str
    cut: int
    verdict: str
    ends_at: int
    review_pct: int | None
    review_count: int
    why: str
    score: float
    url: str
    image: str
    notes: str = ""

    @classmethod
    def from_rec(cls, r: Rec, kind: str) -> "Card":
        i = r.item
        label = verdict_text(r.verdict)
        return cls(i.appid, kind, i.name, i.final_fmt, i.orig_fmt, i.cut, label, i.ends_at, i.review_pct,
                   i.review_count, r.why, round(r.score), i.url, i.cover, notes_for(r))

    @classmethod
    def from_dlc(cls, row, kind: str = "dlc_lowest") -> "Card":
        i = row.item
        label = verdict_text(verdict(i.cut, row.hist))
        owner = t("own_you", h=f"{row.hours:.0f}") if row.owner_kind == "you" else (
            t("own_unplayed") if row.owner_kind == "unplayed" else t("own_family", owner=row.owner))
        return cls(i.appid, kind, i.name, i.final_fmt, i.orig_fmt, i.cut, label, i.ends_at, i.review_pct,
                   i.review_count, f"{short_name(row.base_name, 40)} · {owner}", round(100 * row.score), i.url,
                   i.cover)

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> "Card":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})

    # ---------------------------------------------------------------- pieces

    @property
    def icon(self) -> str:
        return KINDS.get(self.kind, ("✦", ""))[0]

    @property
    def headline(self) -> str:
        return f"{self.icon} {t(KINDS.get(self.kind, ('', 'ev_top'))[1])}"

    def ends_text(self) -> str:
        if not self.ends_at:
            return ""
        secs = self.ends_at - time.time()
        if secs <= 0:
            return ""
        if secs < 86400:
            return t("ends_hours", n=max(1, round(secs / 3600)))
        return t("ends_days", n=round(secs / 86400))

    def reviews_text(self) -> str:
        if self.review_pct is None or not self.review_count:
            return ""
        return t("reviews_short", pct=self.review_pct, n=num(self.review_count))

    def price_line(self) -> str:
        if not self.cut:
            return self.price
        return f"{self.price}  −{self.cut}%"

    def plain(self) -> str:
        lines = [self.title, self.price_line() + (f" · {self.verdict}" if self.verdict else "")]
        meta = " · ".join(x for x in (self.reviews_text(), self.ends_text()) if x)
        if meta:
            lines.append(meta)
        if self.notes:
            lines.append(self.notes)
        if self.why:
            lines.append(f"{t('why')}: {self.why}")
        return "\n".join(lines)


def notes_for(r: Rec, wait: bool = True) -> str:
    """Short annotations shared by every renderer (target hit, bundle, cadence, unshared family copy, elsewhere, accounts, wait)."""
    ex = r.extras
    parts = []
    tgt = ex.get("target")
    if tgt and tgt.get("hit"):
        parts.append("🎯 " + t("note_target"))
    bnd = ex.get("bundle")
    if bnd and bnd.get("badge") and (bnd.get("bundle_discount") or bnd.get("owned_in_set")):
        parts.append(bnd["badge"])
    if r.hist and r.hist.tier == "rare":
        parts.append("◈ " + cadence_badge(r.hist))
    if ex.get("unshared"):
        parts.append(t("note_unshared", owner=ex["unshared"]))
    if ex.get("elsewhere"):
        e = ex["elsewhere"]
        parts.append(t("note_elsewhere", shop=e.shop, pct=e.pct))
    if ex.get("account"):
        parts.append(t("note_account", name=ex["account"]))
    if wait and ex.get("wait"):
        w = ex["wait"]
        parts.append("⏳ " + t("note_wait", sale=sale_name(w.name), days=max(1, (w.start - _today()).days)))
    return " · ".join(parts)


def _today():
    import datetime as dt
    return dt.date.today()


def sale_name(name: str) -> str:
    key = {"Steam Winter Sale": "sale_winter", "Steam Spring Sale": "sale_spring",
           "Steam Summer Sale": "sale_summer", "Steam Autumn Sale": "sale_autumn"}.get(name)
    return t(key) if key else name


# --------------------------------------------------------------------------- renderers

def telegram_caption(c: Card) -> str:
    e = html.escape
    lines = [f"<b>{e(c.headline)}</b>", f"<b><a href=\"{e(c.url)}\">{e(c.title)}</a></b>"]
    price = f"<b>{e(c.price)}</b>"
    if c.cut:
        price += f"  <s>{e(c.orig)}</s>  −{c.cut}%"
    if c.verdict:
        price += f"  ·  {e(c.verdict)}"
    lines.append(price)
    meta = " · ".join(x for x in (c.reviews_text(), c.ends_text()) if x)
    if meta:
        lines.append(e(meta))
    if c.notes:
        lines.append(f"<i>{e(c.notes)}</i>")
    if c.why:
        lines.append(f"{e(t('why_you'))}: {e(c.why)}")
    if c.score:
        filled = max(0, min(5, round(c.score / 20)))
        lines.append(f"{e(t('match'))} {c.score} {'▰' * filled}{'▱' * (5 - filled)}")
    return "\n".join(lines)[:1024]


def discord_embed(c: Card) -> dict:
    fields = []
    if c.cut:
        fields.append({"name": t("col_price"), "value": f"**{c.price}** ~~{c.orig}~~ −{c.cut}%", "inline": True})
    if c.verdict:
        fields.append({"name": t("col_history"), "value": c.verdict, "inline": True})
    if c.ends_text():
        fields.append({"name": t("col_ends"), "value": c.ends_text(), "inline": True})
    desc = "\n".join(x for x in (c.notes and f"*{c.notes}*", c.why and f"{t('why_you')}: {c.why}",
                                 c.reviews_text()) if x)
    return {"title": c.title[:256], "url": c.url, "description": desc[:4000], "color": COLORS.get(c.kind, 0x66C0F4),
            "author": {"name": c.headline}, "fields": fields, "image": {"url": c.image},
            "footer": {"text": f"sift · {t('match')} {c.score}" if c.score else "sift"}}


def email_html(cards: list[Card], title: str) -> str:
    e = html.escape
    rows = []
    for c in cards:
        rows.append(
            f'<tr><td style="padding:12px 0;border-bottom:1px solid #2a3a4a">'
            f'<a href="{e(c.url)}"><img src="{e(c.image)}" width="230" style="border-radius:6px;display:block"></a></td>'
            f'<td style="padding:12px 16px;border-bottom:1px solid #2a3a4a;vertical-align:top">'
            f'<div style="color:#8fb8d8;font-size:12px">{e(c.headline)}</div>'
            f'<a href="{e(c.url)}" style="color:#fff;font-weight:600;font-size:16px;text-decoration:none">{e(c.title)}</a>'
            f'<div style="margin-top:4px"><b style="color:#a4d007">{e(c.price)}</b> '
            f'<s style="color:#8a8a8a">{e(c.orig) if c.cut else ""}</s> {f"−{c.cut}%" if c.cut else ""} '
            f'<span style="color:#66c0f4">{e(c.verdict)}</span></div>'
            f'<div style="color:#9aa;font-size:13px;margin-top:4px">{e(c.notes)}</div>'
            f'<div style="color:#cbd;font-size:13px;margin-top:4px">{e(c.why)}</div></td></tr>')
    return (f'<html><body style="background:#171a21;color:#c7d5e0;font-family:Segoe UI,Arial,sans-serif;padding:24px">'
            f'<h2 style="color:#fff;margin:0 0 12px">{e(title)}</h2><table cellspacing="0" style="width:100%">'
            f'{"".join(rows)}</table><p style="color:#567;font-size:12px">sift</p></body></html>')
