"""sift update: version compare, how sift was installed, the command for each, the binary swap."""
import sys

import pytest

from steamsift import updater


def test_versions_compare_as_numbers():
    assert updater.parse("v0.3.10") > updater.parse("0.3.9") > updater.parse("0.3")
    assert updater.parse("garbage") == (0,)


def test_newer_uses_the_cached_latest(monkeypatch):
    monkeypatch.setattr(updater, "__version__", "0.3.3")
    monkeypatch.setattr(updater, "latest", lambda cached=True: "0.3.4")
    assert updater.newer() == "0.3.4"
    monkeypatch.setattr(updater, "latest", lambda cached=True: "0.3.3")
    assert updater.newer() == ""


@pytest.mark.parametrize("prefix,expected", [
    ("C:/Users/x/AppData/Roaming/uv/tools/steamsift", "uv"),
    ("/home/x/.local/share/uv/tools/steamsift", "uv"),
    ("/home/x/.local/share/pipx/venvs/steamsift", "pipx"),
    ("/usr/lib/python3.12", "pip"),
])
def test_install_method_from_prefix(monkeypatch, tmp_path, prefix, expected):
    monkeypatch.setattr(updater, "__file__", str(tmp_path / "steamsift" / "updater.py"))   # no .git next to it
    monkeypatch.setattr(sys, "prefix", prefix)
    assert updater.method() == expected
    cmd = updater.command(expected)
    assert "steamsift" in cmd


def test_frozen_binary_and_source_checkout(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert updater.method() == "binary"
    monkeypatch.delattr(sys, "frozen")
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("")
    monkeypatch.setattr(updater, "__file__", str(tmp_path / "steamsift" / "updater.py"))
    assert updater.method() == "source"
    assert updater.command("source")[-2:] == ["pull", "--ff-only"]


def test_binary_swap_keeps_the_old_file_when_the_download_is_broken(tmp_path):
    exe = tmp_path / ("sift.exe" if sys.platform == "win32" else "sift")
    exe.write_text("old")
    urls = []

    def download(url, dest):
        urls.append(url)
        dest.write_text("new")

    with pytest.raises(RuntimeError):
        updater.replace_binary("9.9.9", exe, download, verify=lambda p, v: "crashed")
    assert exe.read_text() == "old" and not list(tmp_path.glob("*.part"))
    updater.replace_binary("9.9.9", exe, download, verify=lambda p, v: "")
    assert exe.read_text() == "new" and urls[-1].endswith("/v9.9.9/" + updater.asset_name())
    if sys.platform == "win32":
        assert (tmp_path / "sift.old.exe").read_text() == "old"     # removed on the next start


def test_update_flag_is_the_update_command(monkeypatch):
    from steamsift import cli
    seen = []
    monkeypatch.setattr(cli, "cmd_update", lambda args: seen.append(args.check) or 0)
    assert cli.main(["--update"]) == 0 and cli.main(["update", "--check"]) == 0
    assert seen == [False, True]
