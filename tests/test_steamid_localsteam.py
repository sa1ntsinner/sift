import pytest

from steamsift import localsteam, steamid
from steamsift.steamid import BASE

ID = "76561198012345678"
ACC = int(ID) - BASE


@pytest.mark.parametrize("text,expected", [
    (ID, ("id64", ID)),
    (f"https://steamcommunity.com/profiles/{ID}/", ("id64", ID)),
    (f"steamcommunity.com/profiles/{ID}/games?tab=all", ("id64", ID)),
    (f"[U:1:{ACC}]", ("id64", ID)),
    (f"https://steamcommunity.com/profiles/[U:1:{ACC}]", ("id64", ID)),
    (f"STEAM_0:{ACC % 2}:{ACC // 2}", ("id64", ID)),
    (str(ACC), ("id64", ID)),                                       # friend code
    ("https://steamcommunity.com/id/gabelogannewell/", ("vanity", "gabelogannewell")),
    ("gabelogannewell", ("vanity", "gabelogannewell")),
    (f"https://s.team/p/{steamid.encode_invite(ACC)}", ("id64", ID)),
    (f"https://steamcommunity.com/user/{steamid.encode_invite(ACC)}/", ("id64", ID)),
    ("  <https://steamcommunity.com/id/some_name>  ", ("vanity", "some_name")),
])
def test_parse_every_profile_format(text, expected):
    assert steamid.parse(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "https://example.com/x y", "a"])
def test_parse_rejects_garbage(text):
    assert steamid.parse(text) is None


def test_invite_code_roundtrip():
    for acc in (1, 4242, ACC, 2 ** 32 - 1):
        assert steamid.decode_invite(steamid.encode_invite(acc)) == acc


VDF = r'''
"UserLocalConfigStore"
{
    // comment
    "friends" { "x" "1" }
    "FamilyGroup"
    {
        "version"   "1"
        "name"      "Alex's \"Family\""
        "members"
        {
            "0" { "accountid" "%d" "role" "1" }
            "1" { "AccountID" "12345" "role" "1" }
        }
    }
}
''' % ACC


def test_vdf_parser_handles_nesting_escapes_and_case():
    data = localsteam.parse_vdf(VDF)
    fg = localsteam.ci_get(data, "userlocalconfigstore", "familygroup")
    assert fg["name"] == 'Alex\'s "Family"'
    assert localsteam.ci_get(fg, "members", "1", "accountid") == "12345"


def test_family_is_read_only_from_this_users_folder(tmp_path, monkeypatch):
    root = tmp_path / "Steam"
    mine = root / "userdata" / str(ACC) / "config"
    other = root / "userdata" / "371502987" / "config"
    mine.mkdir(parents=True)
    other.mkdir(parents=True)
    (mine / "localconfig.vdf").write_text(VDF, encoding="utf-8")
    (other / "localconfig.vdf").write_text(VDF.replace("Alex", "Stranger"), encoding="utf-8")
    monkeypatch.setattr(localsteam, "steam_roots", lambda: [root])

    fam = localsteam.family_from_client(ID)
    assert fam["name"].startswith("Alex")
    assert fam["member_steam_ids"] == [ID, steamid.from_account_id(12345)]
    # an account without its own folder must NOT borrow someone else's family
    assert localsteam.family_from_client(steamid.from_account_id(777)) == {}
