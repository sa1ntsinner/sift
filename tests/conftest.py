"""Isolated test environment: own SIFT_HOME, no OS keyring, Steam answered from recorded fixtures."""
import json
import os
import tempfile
from pathlib import Path

_test_state = Path(__file__).resolve().parents[1] / ".pytest_cache"
_test_state.mkdir(exist_ok=True)
os.environ["SIFT_HOME"] = tempfile.mkdtemp(prefix="sift-test-", dir=_test_state)
for var in ("STEAM_API_KEY", "ITAD_API_KEY", "STEAM_ID64", "STEAM_COUNTRY", "STEAM_BALANCE", "SIFT_LANG",
            "SIFT_PROFILE", "SIFT_FAMILY"):
    os.environ.pop(var, None)

import pytest  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    from steamsift import config
    import requests

    def no_network(*args, **kwargs):
        raise AssertionError("Tests must use recorded fixtures, never live HTTP")

    monkeypatch.setattr(requests.sessions.Session, "request", no_network)
    monkeypatch.setattr(config, "_keyring", lambda: None)
    from steamsift import itad, net
    monkeypatch.setattr(itad, "PACE", 0)                 # no pacing against fake endpoints
    monkeypatch.setattr(net, "_hold", {})
    monkeypatch.setattr(config, "_legacy_env_files", lambda: [])
    monkeypatch.setenv("SIFT_LANG", "en")
    config.activate()
    yield


@pytest.fixture
def steam_offline(monkeypatch):
    """Serve IStoreBrowseService/GetItems from fixtures, keyed by the request's country."""
    from steamsift import db, steam

    tags = {int(t["tagid"]): t["name"] for t in load_fixture("tags_english.json")}
    monkeypatch.setattr(steam, "tag_names", lambda lang="english": tags)
    calls = []

    def fake_request(url, params=None, payload=None, **kw):
        assert "GetItems" in url, url
        req = json.loads(params["input_json"])
        cc = req["context"]["country_code"]
        calls.append(cc)
        wanted = {i["appid"] for i in req["ids"]}
        data = load_fixture(f"getitems_{cc}.json")
        items = [it for it in data["response"]["store_items"] if (it.get("appid") or it.get("id")) in wanted]
        return {"response": {"store_items": items}}

    monkeypatch.setattr(steam, "request_json", fake_request)
    # fresh in-memory caches for every test
    for c in db.Cache.all:
        c._data, c._dirty = {}, set()
    return calls
