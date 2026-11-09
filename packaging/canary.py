"""Weekly check that Steam and IsThereAnyDeal still answer in the shape sift reads (see .github/workflows/canary.yml).

Needs no account: Steam's public store only. With ITAD_API_KEY set it also checks the deals list and a price log.
Exit code 1 and one line per broken part, so the workflow can open an issue with them.
"""
import sys

from steamsift import calendar, config, itad
from steamsift.steam import get_items, search_specials

config.activate()
problems = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f": {detail}" if detail else ""))
    if not ok:
        problems.append(name)


ids = search_specials(0, 50)
check("Steam: discounted games list", len(ids) >= 25, f"{len(ids)} games")
items = list(get_items(ids[:20], with_price=True).values())
check("Steam: game details", len(items) >= 15, f"{len(items)} of {len(ids[:20])}")
check("Steam: prices and discounts", sum(1 for i in items if i.cut > 0 and i.final_cents > 0) >= 10)
check("Steam: tags", sum(1 for i in items if len(i.tags) >= 3) >= 10)
check("Steam: reviews", sum(1 for i in items if i.review_count > 0 and i.review_pct) >= 10)
# Valve's partner page does not answer GitHub's runners, and sift works without it (the forecast falls back to the
# game's own rhythm), so a missing calendar is reported but does not fail the check
print(("ok   " if any(e.kind == "sale" for e in calendar.events()) else "warn ") + "Steam: sale calendar")
if config.get_secret("itad_api_key"):
    deals = itad.feed()
    check("ITAD: Steam deals list", len(deals) >= 1000, f"{len(deals)} games")
    sample = list(deals)[:5]
    hist = itad.history(sample, deep=sample, deals=deals)
    check("ITAD: price logs", sum(1 for h in hist.values() if h and h.points) >= 3, f"{len(hist)} of 5")
else:
    print("skip ITAD: no ITAD_API_KEY")
sys.exit(1 if problems else 0)
