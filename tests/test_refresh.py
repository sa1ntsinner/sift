"""Persistence and offline-first regression contracts."""
import pytest
import requests
import sqlite3
import uuid
import datetime as dt

from steamsift import db, net
from helpers import item, make_ctx, racing_fan
from steamsift.engine import Digest
from steamsift.recommender import Rec
from steamsift.tui.app import Data, Loader


@pytest.fixture
def saved_data(monkeypatch):
    from steamsift.tui import state
    monkeypatch.setattr(state, "_snapshots", db.Cache("snapshot-" + uuid.uuid4().hex))
    lib, meta = racing_fan()
    rec = Rec(item(60, "Saved deal"), 0.5, 0.8, 0.0, "like your games", False)
    return Data(make_ctx(lib, meta), Digest([], [rec], 0, 1), saved_at=1234)


def test_cached_first_paint_never_waits_for_network(monkeypatch):
    def network(*args, **kwargs):
        pytest.fail("cached first paint attempted HTTP")

    monkeypatch.setattr(net.SESSION, "get", network)
    db.set_stale_ok(True)
    try:
        assert net.request_json("https://example.com/missing-cache") is None
    finally:
        db.set_stale_ok(False)


def test_cache_only_preview_cannot_replace_good_data_with_missing_values():
    cache = db.Cache("preview-read-only")
    cache.set("history", {"best": 80})
    db.set_stale_ok(True)
    try:
        cache.set("history", {"best": 0})
        cache.set("missing", {})
    finally:
        db.set_stale_ok(False)
    assert cache.get("history") == {"best": 80}
    assert cache.get("missing") is None


def test_forced_refresh_reuses_values_fetched_during_this_refresh():
    cache = db.Cache("refresh-test", volatile=True)
    cache.set("price", 100)
    db.set_refresh(True)
    try:
        assert cache.get("price") is None
        cache.set("price", 90)
        assert cache.get("price") == 90
    finally:
        db.set_refresh(False)


def test_loader_restores_complete_results_without_rebuilding_or_exiting(monkeypatch, saved_data):
    from steamsift.tui import state

    state.save_snapshot(saved_data)
    # A new reader must get persisted bytes, even though the app hasn't exited.
    state._snapshots._data = None

    def rebuild(*args, **kwargs):
        pytest.fail("restoring results rebuilt the engine")

    monkeypatch.setattr("steamsift.engine.Context", rebuild)
    restored = Loader().load(stale=True)
    assert restored.saved_at == 1234
    assert restored.digest.picks[0].item.name == "Saved deal"
    assert restored.digest.picks[0].why == "like your games"
    assert restored.ctx.lib.my_games[1]["name"] == "Assetto Corsa"


def test_failed_steam_request_does_not_replace_good_results(monkeypatch, saved_data):
    from helpers import offline_digest
    from steamsift import engine
    from steamsift.tui import state

    state.save_snapshot(saved_data)
    offline_digest(monkeypatch)
    monkeypatch.setattr(engine, "Context", lambda *args: saved_data.ctx)

    def fail_request(*args, **kwargs):
        raise requests.ConnectionError("offline")

    def search(*args, **kwargs):
        net.request_json("https://store.steampowered.com/search/results/", retries=0)
        return []

    monkeypatch.setattr(net.SESSION, "get", fail_request)
    monkeypatch.setattr(engine, "search_many", search)
    with pytest.raises(RuntimeError, match="Steam"):
        Loader().load()
    assert state.load_snapshot().saved_at == 1234


def test_snapshots_are_isolated_by_region_and_bad_json_is_ignored(monkeypatch, saved_data):
    from steamsift import config
    from steamsift.tui import state

    state.save_snapshot(saved_data)
    monkeypatch.setattr(config.cfg, "country", "DE")
    assert state.load_snapshot() is None
    state._snapshots.set(state._key(), "{broken")
    assert state.load_snapshot() is None


def test_failed_checkpoint_keeps_dirty_data_for_retry(monkeypatch, tmp_path):
    store = db.Database(tmp_path / "test.db")
    monkeypatch.setattr(db, "_db", store)
    monkeypatch.setattr(db.Cache, "all", [])
    cache = db.Cache("checkpoint")
    cache.set("price", 100)
    store.flush()
    cache.set("price", 90)
    store.execute("CREATE TRIGGER fail_write BEFORE INSERT ON kv BEGIN SELECT RAISE(ABORT, 'disk full'); END")
    with pytest.raises(sqlite3.Error):
        store.flush()
    store.execute("DROP TRIGGER fail_write")
    store.flush()
    cache._data = None
    assert cache.get("price") == 90


def test_optional_store_metadata_failure_does_not_reject_a_usable_scan(monkeypatch):
    before = net.steam_failures()

    def fail_request(*args, **kwargs):
        raise requests.ConnectionError("optional metadata unavailable")

    monkeypatch.setattr(net.SESSION, "get", fail_request)
    assert net.request_json("https://store.steampowered.com/api/appdetails", retries=0) is None
    assert net.steam_failures() == before


def test_snapshot_keeps_history_offers_calendar_and_dlc(saved_data):
    from steamsift.calendar import Event
    from steamsift.engine import DlcRow
    from steamsift.itad import Bundle, Elsewhere, History
    from steamsift.tui import state
    from steamsift.tui.app import render_details

    event = Event("Winter Sale", "sale", dt.date(2026, 12, 17), dt.date(2027, 1, 4))
    rec = saved_data.digest.picks[0]
    rec.hist = History(best_cut=80, points=[("2026-10-01", 80)])
    rec.extras = {"sale_next": event, "bundle3p": Bundle("Bundle", "Humble", "https://example.com", 400,
                                                        "USD", None),
                  "elsewhere": Elsewhere("GOG", 20, "https://example.com")}
    saved_data.digest.sale_next = event
    saved_data.dlc = [DlcRow(item(80, "Saved DLC"), "you", "you", 5, "Base", 0.5, 0.8, rec.hist)]
    saved_data.dlc_at = 1235
    before = render_details(rec).plain
    state.save_snapshot(saved_data)
    state._snapshots._data = None
    restored = state.load_snapshot()
    assert render_details(restored.digest.picks[0]).plain == before
    assert restored.digest.sale_next.start == dt.date(2026, 12, 17)
    assert restored.dlc[0].item.name == "Saved DLC" and restored.dlc_at == 1235
