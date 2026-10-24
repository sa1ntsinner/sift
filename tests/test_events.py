"""G5: events are detected, de-duplicated, held in quiet hours, queued for the digest."""
import datetime as dt
import time

import pytest

from helpers import PUZZLE, RACING, item, make_ctx, offline_digest, racing_fan, sale
from steamsift import config, engine, prefs
from steamsift.itad import History
from steamsift.notify import events as ev
from steamsift.notify import runner

PROFILE = "main"


def RARE(cut):
    """A record price that shows up once or twice in two years: HOT."""
    return History(cut, covered_days=730, sales_2y=2, gap_days=300)


@pytest.fixture
def digest(monkeypatch):
    lib, meta = racing_fan()
    lib.wishlist = [{"appid": a, "priority": 0, "date_added": 0} for a in (10, 11, 12, 13)]
    now = int(time.time())
    wish = {10: item(10, "At record low", PUZZLE, cut=80),
            11: item(11, "Not at low", PUZZLE, cut=40),
            12: item(12, "Ends tonight", PUZZLE, cut=30, ends_at=now + 5 * 3600),
            13: item(13, "Target hit", PUZZLE, cut=10, price=400)}
    cands = {20: item(20, "Great racer", RACING, cut=90), 21: item(21, "Meh puzzle", PUZZLE, cut=90)}
    offline_digest(monkeypatch, events=[sale("Steam Winter Sale", dt.date.today() - dt.timedelta(days=1))],
                   history={10: RARE(80), 11: 90, 12: RARE(30), 20: RARE(90),
                            21: History(90, covered_days=730, sales_2y=18, gap_days=40)})   # GREAT: never pings
    prefs.set_target(13, "Target hit", 500)
    ctx = make_ctx(lib, meta, wish, cands)
    d = engine.build_digest(ctx, limit=20, min_discount=0)
    yield d
    prefs.remove_target(13)
    from steamsift.db import db
    for table in ("notified", "pending"):
        db().execute(f"DELETE FROM {table}")


def kinds(events):
    return {(e.kind, e.appid) for e in events}


def test_detect_every_kind(digest):
    n = config.cfg.profile.notify
    n.min_score = 0
    found = kinds(ev.detect(digest, [], n))
    assert ("wish_lowest", 10) in found
    assert ("wish_target", 13) in found and ("wish_lowest", 13) not in found   # most important kind wins
    assert ("ending", 12) in found
    assert ("pick_strong", 20) in found
    assert ("sale_start", 0) in found
    assert not any(a == 11 for _, a in found), "−40% when −90% was seen is not news"
    assert not any(a == 21 for _, a in found), "a GREAT price comes back every few weeks: not news"


def test_events_respect_settings(digest):
    n = config.cfg.profile.notify
    n.min_score, n.events = 0, ["wish_lowest"]
    try:
        assert {k for k, _ in kinds(ev.detect(digest, [], n))} == {"wish_lowest"}
    finally:
        n.events = list(config.DEFAULT_EVENTS)


def test_dedupe_same_price_lower_price_and_expiry(digest):
    n = config.cfg.profile.notify
    n.min_score = 0
    first = ev.fresh(ev.detect(digest, [], n), PROFILE)
    ev.mark(first, PROFILE)
    assert ev.fresh(ev.detect(digest, [], n), PROFILE) == [], "nothing new on the second scan"
    cheaper = [e for e in ev.detect(digest, [], n) if e.appid == 10]
    cheaper[0].price_cents -= 100
    assert ev.fresh(cheaper, PROFILE), "a lower price is news again"
    later = time.time() + ev.RENOTIFY_AFTER + 60
    assert ev.fresh(ev.detect(digest, [], n), PROFILE, now=later), "old news can be repeated after 3 weeks"


@pytest.mark.parametrize("quiet,hhmm,expected", [
    ("23:00-09:00", "23:30", True), ("23:00-09:00", "08:59", True), ("23:00-09:00", "09:00", False),
    ("13:00-14:00", "13:30", True), ("13:00-14:00", "15:00", False), ("", "03:00", False), ("garbage", "3:00", False),
])
def test_quiet_hours(quiet, hhmm, expected):
    h, m = map(int, hhmm.split(":"))
    assert ev.in_quiet(quiet, dt.datetime(2026, 10, 9, h, m)) is expected


def test_digest_due_once_per_day_and_catches_up():
    at = dt.datetime(2026, 10, 9, 19, 30)
    assert ev.digest_due("19:00", at, last_ts=0)
    assert not ev.digest_due("19:00", at, last_ts=at.timestamp() - 60)            # already sent at 19:29
    assert not ev.digest_due("19:00", dt.datetime(2026, 10, 9, 18, 0), last_ts=dt.datetime(2026, 10, 8, 19, 5).timestamp())
    morning = dt.datetime(2026, 10, 10, 8, 0)                                     # PC was off at 19:00
    assert ev.digest_due("19:00", morning, last_ts=dt.datetime(2026, 10, 8, 19, 5).timestamp())


def test_queue_roundtrip_keeps_cards(digest):
    n = config.cfg.profile.notify
    n.min_score = 0
    found = ev.detect(digest, [], n)
    ev.enqueue(found, PROFILE)
    assert ev.pending_count(PROFILE) == len(found)
    cards = ev.take_pending(PROFILE)
    assert [c.kind for c in cards][0] == "wish_target" and ev.pending_count(PROFILE) == 0
    assert cards[0].title == "Target hit" and cards[0].image.endswith("header.jpg")


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "deliver", lambda cards, title, as_digest, channels=None:
                        calls.append((len(cards), as_digest)) or [])
    monkeypatch.setattr(runner, "process_telegram", lambda: 0)
    n = config.cfg.profile.notify
    n.channels, n.min_score, n.quiet, n.paused_until = ["telegram"], 0, "", 0
    yield calls
    n.channels, n.mode, n.quiet = [], "digest", ""


def test_instant_mode_sends_cards_then_list(digest, sent):
    config.cfg.profile.notify.mode = "instant"
    config.cfg.profile.notify.max_cards = 2
    rep = runner.run(digest=digest, dlc=[])
    assert rep.sent == len(rep.events) >= 4
    assert sent[0] == (2, False) and sent[1][1] is True       # burst of cards, the rest as one digest list
    assert runner.run(digest=digest, dlc=[]).sent == 0         # deduped


def test_digest_mode_queues_until_digest_time(digest, sent):
    n = config.cfg.profile.notify
    n.mode, n.digest_time = "digest", "19:00"
    morning = dt.datetime.combine(dt.date.today(), dt.time(9, 0)).timestamp()
    runner._state.set("main:last_digest", morning - 3600)       # yesterday's digest already went out
    rep = runner.run(digest=digest, dlc=[], now=morning)
    assert rep.queued >= 4 and rep.digest_sent == 0 and not sent
    evening = dt.datetime.combine(dt.date.today(), dt.time(19, 5)).timestamp()
    rep = runner.run(digest=digest, dlc=[], now=evening)
    assert rep.digest_sent >= 4 and sent == [(rep.digest_sent, True)]


def test_quiet_hours_hold_instant_alerts(digest, sent):
    n = config.cfg.profile.notify
    n.mode, n.quiet = "instant", "00:00-23:59"
    rep = runner.run(digest=digest, dlc=[])
    assert rep.queued and not rep.sent and not sent
    n.quiet = ""
    rep = runner.run(digest=digest, dlc=[])
    assert rep.digest_sent and sent                              # held alerts delivered when quiet ends


def test_paused_and_no_channels(digest, sent):
    n = config.cfg.profile.notify
    n.paused_until = int(time.time()) + 3600
    assert runner.run(digest=digest, dlc=[]).skipped == "paused"
    n.paused_until, n.channels = 0, []
    assert runner.run(digest=digest, dlc=[]).skipped == "no_channels"
    assert runner.run(digest=digest, dlc=[], dry_run=True).events, "dry-run works without channels"
