"""G11: CI / release workflows, Docker files, PyInstaller spec and the Actions template are valid and wired."""
import tomllib
from pathlib import Path

import yaml

from steamsift import config, schedule
from steamsift.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent


def _wf(path):
    data = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
    return data, data.get("on") or data.get(True)


def test_ci_runs_tests_on_three_oses():
    wf, triggers = _wf(".github/workflows/ci.yml")
    assert "push" in triggers and "pull_request" in triggers
    job = wf["jobs"]["test"]
    assert set(job["strategy"]["matrix"]["os"]) == {"ubuntu-latest", "windows-latest", "macos-latest"}
    runs = " ".join(s.get("run", "") for s in job["steps"])
    assert "pytest" in runs and "pyflakes" in runs


def test_release_builds_pypi_and_binaries():
    wf, triggers = _wf(".github/workflows/release.yml")
    assert triggers["push"]["tags"] == ["v*"]
    pypi = " ".join(str(s) for s in wf["jobs"]["pypi"]["steps"])
    assert "python -m build" in pypi and "twine check" in pypi and "gh-action-pypi-publish" in pypi
    bins = wf["jobs"]["binaries"]
    assert len(bins["strategy"]["matrix"]["include"]) == 3
    assert any("packaging/pyinstaller/sift.spec" in s.get("run", "") for s in bins["steps"])
    assert (ROOT / "packaging/pyinstaller/entry.py").exists()


def test_actions_template_matches_generator_and_cli():
    saved = (ROOT / "packaging/github-actions/sift.yml").read_text(encoding="utf-8")
    assert saved == schedule.actions_workflow(60, "en", "UTC")
    args = build_parser().parse_args(["notify", "run"])
    assert args.cmd == "notify" and args.action == "run"
    # every env var the workflow sets is understood by sift
    env = yaml.safe_load(saved)["jobs"]["notify"]["env"]
    known = set(config.SECRETS.values()) | {"SIFT_HOME", "TZ", "SIFT_LANG", "STEAM_ID64", "STEAM_COUNTRY",
                                            "SIFT_FAMILY", "SIFT_TELEGRAM_CHAT", "SIFT_NTFY_TOPIC",
                                            "SIFT_NOTIFY_MODE"}
    assert set(env) <= known, set(env) - known


def test_dockerfile_and_compose():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'ENTRYPOINT ["sift"]' in docker and 'CMD ["watch"]' in docker and "SIFT_HOME=/data" in docker
    assert "USER sift" in docker, "don't run as root"
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    svc = compose["services"]["sift"]
    assert svc["restart"] == "unless-stopped" and "sift-data:/data" in svc["volumes"]
    assert build_parser().parse_args(["watch"]).cmd == "watch"


def test_pyproject_entry_points_and_data():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = meta["project"]["scripts"]
    assert scripts.get("sift") == "steamsift.cli:entry"
    assert meta["tool"]["setuptools"]["package-data"]["steamsift"] == ["data/*.json"]
    pkgs = set(meta["tool"]["setuptools"]["packages"])
    assert {"steamsift", "steamsift.notify", "steamsift.tui"} <= pkgs
    for pkg in pkgs:
        assert (ROOT / pkg.replace(".", "/") / "__init__.py").exists(), pkg
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")


def test_single_command_ux(capsys):
    from steamsift import cli
    assert cli.main(["notfy"]) == 2
    out = capsys.readouterr().out
    assert "notfy" in out and "sift notify" in out
    from steamsift import query
    assert query.expand(["-b", "gems"], {"dlc"}, {"-b"}) == (["-b", "gems"], [])      # a value, not a macro
    assert query.expand(["dlc", "gems"], {"dlc"}, {"-b"}) == (["dlc", "gems"], [])    # a command's argument
    import pytest
    with pytest.raises(SystemExit):
        cli.main(["help"])                    # same as --help
    assert "usage: sift" in capsys.readouterr().out
