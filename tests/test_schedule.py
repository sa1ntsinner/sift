"""G7: scheduler definitions for every OS, the watch loop, the GitHub Actions template."""
import plistlib
import sys
import xml.etree.ElementTree as ET

import yaml

from steamsift import schedule

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def test_invocation_is_windowless_and_profile_aware(monkeypatch):
    argv = schedule.invocation("main")
    assert argv[-2:] == ["notify", "run"] and argv[1:3] == ["-m", "steamsift"]
    if sys.platform == "win32":
        assert argv[0].lower().endswith("pythonw.exe")
    assert schedule.invocation("friend")[-2:] == ["-p", "friend"]
    assert schedule.task_name("main") == "sift-notify" and schedule.task_name("friend") == "sift-notify-friend"


def test_windows_task_xml():
    xml = schedule.windows_xml(["C:\\Py\\pythonw.exe", "-m", "steamsift", "notify", "run"], 45)
    root = ET.fromstring(xml.replace('encoding="UTF-16"', ""))
    assert root.find(".//t:Repetition/t:Interval", NS).text == "PT45M"
    assert root.find(".//t:StartWhenAvailable", NS).text == "true"            # catch up after sleep
    assert root.find(".//t:MultipleInstancesPolicy", NS).text == "IgnoreNew"
    assert root.find(".//t:Exec/t:Command", NS).text == "C:\\Py\\pythonw.exe"
    assert root.find(".//t:Exec/t:Arguments", NS).text == "-m steamsift notify run"


def test_launchd_plist():
    plist = plistlib.loads(schedule.launchd_plist(["/usr/bin/python3", "-m", "steamsift", "notify", "run"], 60,
                                                  "main").encode())
    assert plist["StartInterval"] == 3600 and plist["RunAtLoad"] is True
    assert plist["ProgramArguments"][-2:] == ["notify", "run"] and plist["Label"].endswith(".main")


def test_systemd_units():
    service, timer = schedule.systemd_units(["/usr/bin/python3", "-m", "steamsift", "notify", "run"], 30, "main")
    assert "ExecStart=/usr/bin/python3 -m steamsift notify run" in service and "Type=oneshot" in service
    assert "OnUnitActiveSec=30min" in timer and "Persistent=true" in timer and "WantedBy=timers.target" in timer


def test_cron_line():
    assert schedule.cron_line(["sift", "notify", "run"], 30, "main").startswith("*/30 * * * * sift notify run")
    assert schedule.cron_line(["sift", "notify", "run"], 120, "x").startswith("17 */2 * * *")
    assert schedule.cron_line(["sift"], 60, "x").endswith("# sift-notify-x")


def test_github_actions_workflow_is_valid_and_wired():
    wf = yaml.safe_load(schedule.actions_workflow(60, "ru", "Europe/Istanbul"))
    triggers = wf.get("on") or wf.get(True)                 # PyYAML parses the bare `on:` key as True
    assert triggers["schedule"][0]["cron"] == "17 * * * *" and "workflow_dispatch" in triggers
    job = wf["jobs"]["notify"]
    env = job["env"]
    for secret in ("STEAM_ID64", "STEAM_API_KEY", "STEAM_COUNTRY", "SIFT_TELEGRAM_TOKEN", "SIFT_TELEGRAM_CHAT"):
        assert secret in env and "secrets." in env[secret]
    runs = [s.get("run", "") for s in job["steps"]]
    assert "sift notify run" in runs and any("pip install" in r for r in runs)
    assert env["SIFT_HOME"].endswith("/.sift") and env["TZ"] == "Europe/Istanbul"


def test_watch_loop_iterates(monkeypatch):
    from steamsift.notify import runner
    runs = []
    monkeypatch.setattr(runner, "run", lambda: runs.append(1) or runner.Report())
    monkeypatch.setattr(runner, "telegram", lambda: None)
    slept = []
    monkeypatch.setattr(schedule.time, "time", iter(range(0, 100_000, 10)).__next__)
    schedule.watch(every=1, iterations=3, on_report=lambda r: None, sleep=slept.append)
    assert len(runs) == 3 and slept
