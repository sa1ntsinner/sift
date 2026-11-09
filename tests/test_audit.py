"""sift judges its own HOT calls and takes HOT back when they stop holding or the price data looks wrong."""
import datetime as dt
from types import SimpleNamespace as NS

from steamsift import audit
from steamsift.db import db
from steamsift.itad import History
from steamsift.recommender import Verdict

TODAY = dt.date(2026, 11, 9)


def rec(appid, kind="hot", runs=(), covered=730):
    h = History(50, covered_days=covered, regular_cents=2000, low_2y_cents=1000, runs=[list(r) for r in runs])
    return NS(item=NS(appid=appid, cut=50), hist=h, verdict=Verdict(kind, "atl", 0))


def ago(n):
    return (TODAY - dt.timedelta(days=n)).isoformat()


def test_hot_calls_are_written_down_once_and_judged_from_later_logs():
    db().execute("DELETE FROM calls")
    assert audit.review([rec(1), rec(2), rec(3, "great")], TODAY - dt.timedelta(days=200)) == ""
    assert audit.review([rec(1), rec(2)], TODAY - dt.timedelta(days=199)) == ""           # the same sale: one call
    assert len(db().execute("SELECT * FROM calls")) == 2
    # 200 days on: game 1 had a sale 20% cheaper two months after the call, game 2 never beat it
    audit.review([rec(1, "ok", runs=[(ago(140), 800)]), rec(2, "ok", runs=[(ago(140), 1000)])], TODAY)
    assert audit.record() == (2, 1)
    assert dict(db().execute("SELECT appid, outcome FROM calls")) == {1: "bad", 2: "good"}


def test_a_poor_record_takes_hot_back_until_it_recovers():
    db().execute("DELETE FROM calls")
    for n in range(40):
        db().execute("INSERT INTO calls VALUES (?,?,?,?)", (100 + n, ago(300), 1000, "bad" if n < 20 else "good"))
    r = rec(1)
    assert audit.review([r], TODAY) == "record"
    assert (r.verdict.kind, r.verdict.reason) == ("great", "unsure_record")
    db().execute("UPDATE calls SET outcome='good'")
    r = rec(1)
    assert audit.review([r], TODAY) == "" and r.verdict.kind == "hot"


def test_a_sale_where_everything_is_hot_is_not_believed():
    db().execute("DELETE FROM calls")
    recs = [rec(n, "hot" if n % 2 else "ok") for n in range(1, 301)]
    assert audit.review(recs, TODAY) == "mix"
    assert not any(r.verdict.kind == "hot" for r in recs)
    few = [rec(n, "hot" if n % 20 == 0 else "ok") for n in range(1, 301)]
    assert audit.review(few, TODAY) == "" and sum(r.verdict.kind == "hot" for r in few) == 15
    db().execute("DELETE FROM calls")
