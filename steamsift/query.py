"""What to show: one query object behind `sift` flags, the app's filters and macros.

    sift -b 2 -g indie --lowest            # flags → Query
    sift macro add cheap -b 2 -g indie --lowest
    sift cheap                             # a macro is just saved flags; combine freely: sift cheap gems -d 80

Macros live in config.toml as plain strings, so they're easy to write by hand too:

    [macros]
    cheap = "-b 2 -g indie --lowest"
"""
from __future__ import annotations

import argparse
import difflib
import shlex
import time
from dataclasses import dataclass, field, fields

from . import config
from .i18n import t

TABS = ("picks", "discover", "wish", "dlc")
SORTS = ("deal", "cut", "price", "rating", "ends", "new", "match")
VERDICT_RANK = {"hot": 0, "great": 1, "ok": 2, "meh": 3, "nope": 4}
SORT_ALIASES = {"score": "deal", "atl": "deal", "rarity": "deal", "deal_value": "deal",
                "discount": "cut", "taste": "match"}

# Ready-made macros (a user macro with the same name wins).
BUILTIN_MACROS = {
    "lows": "--lowest --min-rating 80",
    "2y": "--2y-low --min-rating 80",
    "rare": "--rare --min-rating 80",
    "bundles": "--bundle --min-rating 75",
    "gems": "-x --min-rating 93 --min-reviews 150 --max-reviews 6000",
    "acclaimed": "-x --min-rating 95 --min-reviews 5000",
    "ending": "--ending 2 --sort ends",
    "deep": "-d 75 --min-rating 75 --sort cut",
}


class QueryError(ValueError):
    pass


@dataclass
class Query:
    tab: str = ""                         # picks | discover | wish | dlc ("" = default view)
    max_price: float | None = None        # None = profile budget · 0 = no cap
    min_cut: int | None = None            # None = profile min discount
    lowest: bool = False                  # ★ only the deepest Steam discount ever (ATL)
    low_2y: bool = False                  # ◆ at or below 2-year low (2YL)
    near: bool = False                    # ◇ within 10 points of ATL
    buy: bool = False
    rare: bool = False                    # ◈ only rare discounts / infrequent sales
    bundle: bool = False                  # 📦 only bundles / Complete-the-Set / multi-game packages
    tags: list[str] = field(default_factory=list)      # each must match; "A|B" = either
    no_tags: list[str] = field(default_factory=list)
    min_rating: int = 0                   # % positive reviews
    min_reviews: int = 0
    max_reviews: int = 0
    min_score: int = 0
    deck: bool = False
    no_ea: bool = False
    my_lang: bool = False
    family: bool | None = None            # also games the Steam Family shares (None = the `family` setting)
    since: int = 0                        # released in or after this year
    ending: int = 0                       # discount ends within N days
    sort: str = "deal"
    macros: list[str] = field(default_factory=list)   # names applied (display only)

    def __post_init__(self) -> None:
        self.sort = SORT_ALIASES.get(self.sort, self.sort)

    # ------------------------------------------------------------ effective values

    def shows_family(self) -> bool:
        return config.cfg.profile.filters.family if self.family is None else self.family

    def price_cap(self) -> float | None:
        cap = self.max_price if self.max_price is not None else config.cfg.budget
        return cap or None

    def cut_floor(self) -> int:
        return self.min_cut if self.min_cut is not None else config.cfg.min_discount

    def is_default(self) -> bool:
        return self.filters_key() == Query(tab=self.tab, sort=self.sort).filters_key()

    def filters_key(self) -> tuple:
        return tuple(getattr(self, f.name) if not isinstance(getattr(self, f.name), list)
                     else tuple(getattr(self, f.name)) for f in fields(self) if f.name not in ("tab", "sort", "macros"))

    # ------------------------------------------------------------ matching

    def match(self, item, hist=None, score: float | None = None) -> bool:
        cap = self.price_cap()
        if cap is not None and item.price > cap:
            return False
        if item.cut < self.cut_floor():
            return False
        best = hist.best_cut if hist is not None else 0
        if self.lowest and not (best > 0 and item.cut >= best):
            return False
        if self.low_2y and not (hist is not None and hist.is_2y_low(item.cut)):
            return False
        if self.near and not (best > 0 and item.cut >= best - 10):
            return False
        if self.rare and not (hist is not None and hist.tier == "rare"):
            return False
        if self.bundle and not getattr(item, "is_bundle", False):
            return False
        if self.tags or self.no_tags:
            top = {tg.lower() for tg, _ in sorted(item.tags.items(), key=lambda kv: -kv[1])[:12]}
            for group in self.tags:
                if not any(opt.lower() in top for opt in group.split("|")):
                    return False
            if any(x.lower() in top for x in self.no_tags):
                return False
        pct = item.review_pct or 0
        if pct < self.min_rating or item.review_count < self.min_reviews:
            return False
        if self.max_reviews and item.review_count > self.max_reviews:
            return False
        if self.min_score and score is not None and score < self.min_score:
            return False
        if self.deck and item.deck not in (2, 3):
            return False
        if self.no_ea and item.early_access:
            return False
        if self.my_lang and item.languages:
            from .engine import ELANG
            if not item.languages.get(str(ELANG.get(config.cfg.steam_lang, 0))):
                return False
        if self.since and (not item.release or time.localtime(item.release).tm_year < self.since):
            return False
        if self.ending:
            left = (item.ends_at or 0) - time.time()
            if not 0 < left <= self.ending * 86400:
                return False
        return True

    def sort_key(self):
        s = SORT_ALIASES.get(self.sort, self.sort)
        return {
            "score": lambda item, score: -(score or 0),
            "price": lambda item, score: item.final_cents,
            "cut": lambda item, score: -item.cut,
            "rating": lambda item, score: -((item.review_pct or 0) * 1000 + min(999, item.review_count // 100)),
            "ends": lambda item, score: item.ends_at or 2 ** 40,
            "new": lambda item, score: -(item.release or 0),
        }.get(s, lambda item, score: -(score or 0))

    def _rec_sort_key(self, r):
        s = SORT_ALIASES.get(self.sort, self.sort)
        if s == "deal":
            # most worthwhile first: verdict, then deal score, then how well reviewed, then the cut
            from .recommender import deal_value, verdict, wilson_lower
            v = getattr(r, "verdict", None)
            kind = v.kind if v is not None and hasattr(v, "kind") else verdict(r.item.cut, getattr(r, "hist", None)).kind
            ds = getattr(r, "deal_score", None)
            if ds is None:
                ds = deal_value(r.item.cut, getattr(r, "hist", None), r.item) * 100
            reviews = wilson_lower(r.item.review_pct, r.item.review_count) or 0.0
            return (VERDICT_RANK.get(kind, len(VERDICT_RANK)), -round(ds), -reviews, -r.item.cut)
        if s == "match":
            aff = getattr(r, "affinity", 0.0)
            cos = getattr(r, "cos", 0.0)
            return (-aff, -cos, -(_score(r) or 0))
        key = self.sort_key()
        return key(r.item, _score(r))

    def apply(self, recs: list) -> list:
        """Filter + sort Recs (or anything with .item / .hist / .score)."""
        out = [r for r in recs if self.match(r.item, getattr(r, "hist", None), _score(r))
               and (not self.buy or getattr(getattr(r, "verdict", None), "kind", "") == "hot")
               and (self.shows_family() or not getattr(r, "extras", {}).get("family"))]
        return sorted(out, key=self._rec_sort_key)

    # ------------------------------------------------------------ display

    def chips(self) -> list[str]:
        """Human-readable, localized summary: ['≤ $2.00', '★ record low', 'indie', …]."""
        from .steam import local_tag
        from .ui import money
        out = []
        if self.family:
            out.append(t("q_family"))
        if self.max_price is not None:
            out.append(t("q_price", p=money(self.max_price)) if self.max_price else t("q_any_price"))
        if self.min_cut is not None:
            out.append(t("q_cut", n=self.min_cut))
        if self.lowest:
            out.append(t("q_lowest"))
        elif self.low_2y:
            out.append(t("q_low_2y"))
        elif self.near:
            out.append(t("q_near"))
        if self.rare:
            out.append(t("q_rare"))
        if self.bundle:
            out.append(t("q_bundle"))
        for group in self.tags:
            out.append(" | ".join(local_tag(x).lower() for x in group.split("|")))
        if self.no_tags:
            out.append(t("q_no_tags", tags=", ".join(local_tag(x).lower() for x in self.no_tags)))
        if self.min_rating:
            out.append(t("q_rating", n=self.min_rating))
        if self.min_reviews and self.max_reviews:
            out.append(t("q_reviews_between", a=self.min_reviews, b=self.max_reviews))
        elif self.min_reviews:
            out.append(t("q_reviews_min", n=self.min_reviews))
        elif self.max_reviews:
            out.append(t("q_reviews_max", n=self.max_reviews))
        if self.min_score:
            out.append(t("q_score", n=self.min_score))
        if self.deck:
            out.append(t("ui_f_deck"))
        if self.no_ea:
            out.append(t("ui_f_no_ea"))
        if self.my_lang:
            out.append(t("ui_f_lang"))
        if self.since:
            out.append(t("q_since", y=self.since))
        if self.ending:
            out.append(t("q_ending", n=self.ending))
        return out

    def to_args(self) -> str:
        """The flags that reproduce this query (for saving as a macro)."""
        a = []
        if self.tab:
            a.append({"picks": "-t", "discover": "-x", "wish": "-w", "dlc": "--dlc"}[self.tab])
        if self.family is not None:
            a.append("--family" if self.family else "--no-family")
        if self.max_price is not None:
            a += ["-b", f"{self.max_price:g}"]
        if self.min_cut is not None:
            a += ["-d", str(self.min_cut)]
        if self.lowest:
            a.append("--lowest")
        if self.low_2y:
            a.append("--2y-low")
        if self.near:
            a.append("--near")
        if self.buy:
            a.append("--hot")
        if self.rare:
            a.append("--rare")
        if self.bundle:
            a.append("--bundle")
        for g in self.tags:
            a += ["-g", g]
        for g in self.no_tags:
            a += ["-G", g]
        for flag, val in (("--min-rating", self.min_rating), ("--min-reviews", self.min_reviews),
                          ("--max-reviews", self.max_reviews), ("--min-score", self.min_score),
                          ("--since", self.since), ("--ending", self.ending)):
            if val:
                a += [flag, str(val)]
        for flag, on in (("--deck", self.deck), ("--no-ea", self.no_ea), ("--my-lang", self.my_lang)):
            if on:
                a.append(flag)
        if self.sort != "deal":
            a += ["--sort", self.sort]
        return shlex.join(a)


def _score(r) -> float | None:
    s = getattr(r, "score", None)
    return s if isinstance(s, (int, float)) and getattr(r, "mode", None) is not None else None


# --------------------------------------------------------------------------- flags

ALL_SORT_CHOICES = (*SORTS, *SORT_ALIASES.keys())


def add_view_args(p: argparse.ArgumentParser) -> None:
    """Everything `sift` (and a macro) can say about what to show. -b / -d / -l live in cli.common()."""
    g = p.add_argument_group("what to show")
    g.add_argument("-w", "--wishlist", action="store_true", help="wishlist deals")
    g.add_argument("-t", "--top", action="store_true", help="picked for you")
    g.add_argument("-x", "--discover", action="store_true", help="discover: great deals outside your usual genres")
    g.add_argument("--dlc", action="store_true", help="DLC for games you or your family own")
    f = p.add_argument_group("filters")
    f.add_argument("-L", "--lowest", "--atl", action="store_true", help="★ only all-time record lows (ATL)")
    f.add_argument("--2y-low", "--2yl", dest="low_2y", action="store_true", help="◆ at or below 2-year low (2YL)")
    f.add_argument("--near", action="store_true", help="◇ at or near the record low")
    f.add_argument("--hot", "--buy", dest="buy", action="store_true", help="only HOT deals")
    f.add_argument("--family", dest="family", action="store_true", default=None,
                   help="also games your Steam Family shares (marked ⌂)")
    f.add_argument("--no-family", dest="family", action="store_false", help="hide games your Steam Family shares")
    f.add_argument("--rare", action="store_true", help="◈ only rare discounts / infrequent sales")
    f.add_argument("--bundle", action="store_true", help="📦 only bundles / Complete-the-Set deals")
    f.add_argument("-g", "--tag", action="append", default=[], metavar="TAG",
                   help='must have this tag (repeat for more, "rpg|strategy" = either); RU/EN names work')
    f.add_argument("-G", "--no-tag", action="append", default=[], metavar="TAG", help="must not have this tag")
    f.add_argument("--min-rating", type=int, default=0, metavar="PCT", help="minimum %% positive reviews")
    f.add_argument("--min-reviews", type=int, default=0, metavar="N")
    f.add_argument("--max-reviews", type=int, default=0, metavar="N", help="lesser-known games")
    f.add_argument("--min-score", type=int, default=0, metavar="N", help="minimum match / discovery score")
    f.add_argument("--deck", action="store_true", help="works on Steam Deck")
    f.add_argument("--no-ea", action="store_true", help="no early access")
    f.add_argument("--my-lang", action="store_true", help="in your language")
    f.add_argument("--since", type=int, default=0, metavar="YEAR", help="released in YEAR or later")
    f.add_argument("--ending", type=int, default=0, metavar="DAYS", help="discount ends within DAYS")
    f.add_argument("-s", "--sort", choices=ALL_SORT_CHOICES, default="deal", metavar="{" + ",".join(SORTS) + "}")


def from_args(args: argparse.Namespace) -> Query:
    tab = ("discover" if args.discover else "wish" if args.wishlist else "picks" if args.top
           else "dlc" if getattr(args, "dlc", False) else "")
    if getattr(args, "min_discount", None) is not None and not 0 <= args.min_discount <= 100:
        raise QueryError(t("q_bad_cut"))
    return Query(
        tab=tab, max_price=getattr(args, "budget", None), min_cut=getattr(args, "min_discount", None),
        lowest=args.lowest, low_2y=getattr(args, "low_2y", False), near=args.near,
        buy=getattr(args, "buy", False), family=getattr(args, "family", None), rare=getattr(args, "rare", False), bundle=getattr(args, "bundle", False),
        tags=[resolve_tags(g) for g in _split(args.tag)], no_tags=[resolve_tag(x) for x in _split(args.no_tag, "|")],
        min_rating=args.min_rating, min_reviews=args.min_reviews, max_reviews=args.max_reviews,
        min_score=args.min_score, deck=args.deck, no_ea=args.no_ea, my_lang=args.my_lang,
        since=args.since, ending=args.ending, sort=SORT_ALIASES.get(args.sort, args.sort),
    )


def _split(values: list[str], extra: str = "") -> list[str]:
    """['indie,horror'] → ['indie', 'horror'] (commas = separate filters)."""
    out = []
    for v in values:
        for part in v.replace(extra, ",").split(",") if extra else v.split(","):
            if part.strip():
                out.append(part.strip())
    return out


def view_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sift", add_help=False, exit_on_error=False)
    add_view_args(p)
    p.add_argument("-b", "--budget", type=float, default=None)
    p.add_argument("-d", "--min-discount", type=int, default=None)
    return p


def parse(text: str | list[str]) -> Query:
    """Flags (a macro body, or what the app's filter box saves) → Query."""
    argv = shlex.split(text) if isinstance(text, str) else list(text)
    try:
        args, extra = view_parser().parse_known_args(argv)
    except (argparse.ArgumentError, SystemExit) as e:
        raise QueryError(str(e)) from None
    if extra:
        raise QueryError(t("q_unknown_flags", flags=" ".join(extra)))
    return from_args(args)


# --------------------------------------------------------------------------- tags

def _tag_index(extra: str = "") -> dict[str, str]:
    """lower-case English or localized tag name → English tag name."""
    from .steam import tag_names
    en = tag_names("english")
    out = {name.lower(): name for name in en.values()}
    for lang in dict.fromkeys(x for x in (config.cfg.steam_lang, extra) if x and x != "english"):
        for tid, name in tag_names(lang).items():
            if tid in en:
                out.setdefault(name.lower(), en[tid])
    return out


def resolve_tag(text: str) -> str:
    """'инди' / 'indie' / 'roguel' → 'Indie' / 'Indie' / 'Roguelike'."""
    want = text.strip().lower()
    # a Cyrillic tag works whatever the interface language (macros saved in Russian keep working in English)
    idx = _tag_index("" if want.isascii() else "russian")
    if not idx or want in idx:
        return idx.get(want, text.strip())
    starts = sorted((k for k in idx if k.startswith(want)), key=len)
    if starts:
        return idx[starts[0]]
    close = difflib.get_close_matches(want, list(idx), n=3, cutoff=0.75)
    if len(close) == 1 or (close and difflib.SequenceMatcher(None, want, close[0]).ratio() > 0.85):
        return idx[close[0]]
    hint = difflib.get_close_matches(want, list(idx), n=3, cutoff=0.5)
    raise QueryError(t("q_bad_tag", tag=text) + (f"  →  {', '.join(hint)}" if hint else ""))


def resolve_tags(group: str) -> str:
    return "|".join(resolve_tag(x) for x in group.split("|") if x.strip())


# --------------------------------------------------------------------------- macros

def user_macros() -> dict[str, str]:
    return dict(config.cfg.settings.macros)


def all_macros() -> dict[str, tuple[str, bool]]:
    """name → (flags, is_builtin)."""
    out = {k: (v, True) for k, v in BUILTIN_MACROS.items()}
    out.update({k: (v, False) for k, v in user_macros().items()})
    return out


def save_macro(name: str, flags: str, reserved: set[str]) -> Query:
    name = name.strip().lower()
    if not name or not name.replace("-", "").replace("_", "").isalnum() or name.startswith("-"):
        raise QueryError(t("m_bad_name", name=name))
    if name in reserved:
        raise QueryError(t("m_reserved", name=name))
    q = parse(flags)                      # validate before saving
    s = config.cfg.settings
    s.macros[name] = flags.strip()
    s.save()
    return q


def remove_macro(name: str) -> bool:
    s = config.cfg.settings
    if name in s.macros:
        del s.macros[name]
        s.save()
        return True
    return False


def expand(argv: list[str], commands: set[str], takes_value: set[str]) -> tuple[list[str], list[str]]:
    """Replace macro names in argv with their flags: (new argv, macro names used). Later flags win."""
    macros = all_macros()
    out, used = [], []
    for i, tok in enumerate(argv):
        prev = argv[i - 1] if i else ""
        is_value = prev in takes_value and not _has_inline_value(prev)
        if not tok.startswith("-") and not is_value and tok in commands:
            return out + argv[i:], used       # a real command: the rest is its arguments (`sift info gems`)
        if not tok.startswith("-") and not is_value and tok in macros:
            out += shlex.split(macros[tok][0])
            used.append(tok)
        else:
            out.append(tok)
    return out, used


def _has_inline_value(opt: str) -> bool:
    return "=" in opt
