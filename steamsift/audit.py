"""sift checks its own advice, so wrong data or rules that stopped fitting Steam do not turn into bad advice.

HOT says "buy now: the next sale is usually dearer". Every HOT shown is written down, and when the game's price log
later covers the months after it, the call is judged: was the game clearly cheaper within four months? In the
backtest (8,700 sale starts, 2026-11) the next sale was cheaper after 9% of HOT calls. When your own record says
it happens far more often, or when a suspicious share of a sale comes out HOT (a price source gone wrong looks
exactly like that), HOT is shown as GREAT with the reason, until the record is good again. Nobody has to notice.
"""
from __future__ import annotations

import datetime as dt

from .db import db, stale_ok
from .recommender import Verdict

WINDOW = 120                    # days after a HOT call in which a clearly cheaper sale makes it a wrong call
CHEAPER = 0.88                  # "clearly cheaper": 12% under the price called HOT
MIN_JUDGED, MAX_BAD = 30, 0.30  # the record counts from 30 judged calls; over 30% wrong = not trusted
MIN_POOL, MAX_HOT = 200, 0.15   # of 200+ games judged by price, at most 15% can be HOT (the backtest: 5%)


def _judge(day: dt.date, cents: int, hist, today: dt.date) -> str:
    """'bad' | 'good' | '' (not known yet)."""
    for start, low in hist.runs:                                  # finished sales in the log
        if 0 < (dt.date.fromisoformat(start) - day).days <= WINDOW and low and low <= cents * CHEAPER:
            return "bad"
    covered = hist.covered_days >= (today - day).days             # the log reaches back to the call
    return "good" if covered and (today - day).days > WINDOW else ""


def record() -> tuple[int, int]:
    """(calls judged, of them wrong) in the last two years."""
    since = (dt.date.today() - dt.timedelta(days=730)).isoformat()
    rows = db().execute("SELECT outcome, COUNT(*) FROM calls WHERE day>? AND outcome!='' GROUP BY outcome", (since,))
    n = dict(rows)
    return n.get("good", 0) + n.get("bad", 0), n.get("bad", 0)


def review(recs: list, today: dt.date | None = None) -> str:
    """Write down today's HOT calls, judge the old ones these games' logs can answer, and take HOT back when it is
    not to be trusted. Returns why ('record' | 'mix') or ''."""
    today = today or dt.date.today()
    priced = [r for r in recs if r.item.cut > 0 and r.hist and r.hist.by_price()]
    hot = [r for r in priced if r.verdict.kind == "hot"]
    if not stale_ok():
        open_calls = {a: (dt.date.fromisoformat(d), c) for a, d, c in
                      db().execute("SELECT appid, day, cents FROM calls WHERE outcome=''")}
        for r in recs:
            call = open_calls.get(r.item.appid)
            if call and r.hist and r.hist.runs is not None:
                out = _judge(call[0], call[1], r.hist, today)
                if out:
                    db().execute("UPDATE calls SET outcome=? WHERE appid=? AND outcome=''", (out, r.item.appid))
        for r in hot:
            if r.item.appid not in open_calls:
                db().execute("INSERT INTO calls VALUES (?,?,?,'')",
                             (r.item.appid, today.isoformat(), r.hist.now_cents(r.item.cut)))
    judged, bad = record()
    why = ""
    if judged >= MIN_JUDGED and bad / judged > MAX_BAD:
        why = "record"
    elif len(priced) >= MIN_POOL and len(hot) / len(priced) > MAX_HOT:
        why = "mix"
    if why:
        for r in recs:
            if r.verdict.kind == "hot":
                r.verdict = Verdict("great", f"unsure_{why}", 0)
    return why
