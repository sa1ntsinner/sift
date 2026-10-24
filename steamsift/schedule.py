"""Run `sift notify run` on a schedule: Windows Task Scheduler, macOS launchd, systemd user timers, cron.

Plus `sift watch` (a foreground loop with instant Telegram buttons) and a GitHub Actions template.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.sax.saxutils import escape

from . import config

LABEL = "com.steamsift.notify"


def task_name(profile: str) -> str:
    return "sift-notify" if profile == "main" else f"sift-notify-{profile}"


def invocation(profile: str, hidden: bool = True) -> list[str]:
    """argv that runs one notification scan for `profile`, without a console window on Windows."""
    args = ["notify", "run"] + ([] if profile == "main" else ["-p", profile])
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    exe = Path(sys.executable)
    if sys.platform == "win32" and hidden:
        pyw = exe.with_name("pythonw.exe")
        if pyw.exists():
            exe = pyw
    return [str(exe), "-m", "steamsift", *args]


def _quote_win(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv)


# --------------------------------------------------------------------------- Windows

def windows_xml(argv: list[str], every: int) -> str:
    """Task Scheduler XML: repeat every N minutes, catch up after sleep/shutdown, never run twice at once."""
    if getattr(sys, "frozen", False):
        # A frozen console exe would flash a window: launch it through a hidden VBScript shim.
        shim = config.CONFIG_DIR / "sift-hidden.vbs"
        shim.write_text('CreateObject("WScript.Shell").Run "' + _quote_win(argv).replace('"', '""') + '", 0, False\n',
                        encoding="utf-8")
        command, arguments = "wscript.exe", f'"{shim}"'
    else:
        command, arguments = argv[0], _quote_win(argv[1:])
    start = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + 120))
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>sift: Steam deals that match your taste</Description></RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Repetition><Interval>PT{int(every)}M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{escape(command)}</Command><Arguments>{escape(arguments)}</Arguments></Exec>
  </Actions>
</Task>
"""


# --------------------------------------------------------------------------- macOS

def launchd_plist(argv: list[str], every: int, profile: str) -> str:
    args = "".join(f"\n      <string>{escape(a)}</string>" for a in argv)
    log = escape(str(config.STATE_DIR / f"notify-{profile}.log"))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key><string>{LABEL}.{escape(profile)}</string>
    <key>ProgramArguments</key>
    <array>{args}
    </array>
    <key>StartInterval</key><integer>{int(every) * 60}</integer>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key><string>{log}</string>
    <key>StandardErrorPath</key><string>{log}</string>
  </dict>
</plist>
"""


# --------------------------------------------------------------------------- Linux

def systemd_units(argv: list[str], every: int, profile: str) -> tuple[str, str]:
    exec_line = " ".join(f'"{a}"' if " " in a else a for a in argv)
    service = f"""[Unit]
Description=sift: Steam deals that match your taste ({profile})
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart={exec_line}
"""
    timer = f"""[Unit]
Description=Run sift notifications every {every} minutes ({profile})

[Timer]
OnBootSec=3min
OnUnitActiveSec={int(every)}min
Persistent=true

[Install]
WantedBy=timers.target
"""
    return service, timer


def cron_line(argv: list[str], every: int, profile: str) -> str:
    cmd = " ".join(f"'{a}'" if " " in a else a for a in argv)
    minute = "*/" + str(every) if every < 60 else "17"
    hours = "*" if every <= 60 else f"*/{max(1, every // 60)}"
    return f"{minute} {hours} * * * {cmd} >/dev/null 2>&1  # {task_name(profile)}"


# --------------------------------------------------------------------------- install / remove / status

def _run(argv: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=60,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **kw)


def _systemd_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"


def enable(profile: str, every: int) -> tuple[bool, str]:
    argv = invocation(profile)
    name = task_name(profile)
    if sys.platform == "win32":
        xml = Path(tempfile.gettempdir()) / f"{name}.xml"
        xml.write_text(windows_xml(argv, every), encoding="utf-16")
        r = _run(["schtasks", "/Create", "/TN", name, "/XML", str(xml), "/F"])
        xml.unlink(missing_ok=True)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.{profile}.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(launchd_plist(argv, every, profile), encoding="utf-8")
        uid = os.getuid()
        _run(["launchctl", "bootout", f"gui/{uid}", str(path)])
        r = _run(["launchctl", "bootstrap", f"gui/{uid}", str(path)])
        return r.returncode == 0, str(path)
    if shutil.which("systemctl"):
        d = _systemd_dir()
        d.mkdir(parents=True, exist_ok=True)
        service, timer = systemd_units(argv, every, profile)
        (d / f"{name}.service").write_text(service, encoding="utf-8")
        (d / f"{name}.timer").write_text(timer, encoding="utf-8")
        _run(["systemctl", "--user", "daemon-reload"])
        r = _run(["systemctl", "--user", "enable", "--now", f"{name}.timer"])
        if r.returncode == 0:
            return True, f"{d / name}.timer"
    if shutil.which("crontab"):
        current = _run(["crontab", "-l"]).stdout
        lines = [ln for ln in current.splitlines() if not ln.endswith(f"# {name}")]
        lines.append(cron_line(argv, every, profile))
        r = subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", capture_output=True, text=True)
        return r.returncode == 0, "crontab"
    return False, "no scheduler found (systemd / cron)"


def disable(profile: str) -> tuple[bool, str]:
    name = task_name(profile)
    if sys.platform == "win32":
        r = _run(["schtasks", "/Delete", "/TN", name, "/F"])
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.{profile}.plist"
        _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)])
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed, str(path)
    ok = False
    if shutil.which("systemctl"):
        _run(["systemctl", "--user", "disable", "--now", f"{name}.timer"])
        for ext in ("timer", "service"):
            p = _systemd_dir() / f"{name}.{ext}"
            ok = ok or p.exists()
            p.unlink(missing_ok=True)
        _run(["systemctl", "--user", "daemon-reload"])
    if shutil.which("crontab"):
        current = _run(["crontab", "-l"]).stdout
        kept = [ln for ln in current.splitlines() if not ln.endswith(f"# {name}")]
        if len(kept) != len(current.splitlines()):
            subprocess.run(["crontab", "-"], input="\n".join(kept) + "\n", capture_output=True, text=True)
            ok = True
    return ok, name


def status(profile: str) -> tuple[bool, str]:
    name = task_name(profile)
    if sys.platform == "win32":
        r = _run(["schtasks", "/Query", "/TN", name, "/FO", "LIST", "/V"])
        if r.returncode != 0:
            return False, ""
        info = {k.strip(): v.strip() for k, _, v in (ln.partition(":") for ln in r.stdout.splitlines()) if v}
        nxt = info.get("Next Run Time") or info.get("Время следующего запуска") or ""
        return True, nxt
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.{profile}.plist"
        return path.exists(), str(path) if path.exists() else ""
    if shutil.which("systemctl") and (_systemd_dir() / f"{name}.timer").exists():
        r = _run(["systemctl", "--user", "list-timers", f"{name}.timer", "--no-pager"])
        return True, r.stdout.splitlines()[1].strip() if len(r.stdout.splitlines()) > 1 else ""
    if shutil.which("crontab"):
        found = [ln for ln in _run(["crontab", "-l"]).stdout.splitlines() if ln.endswith(f"# {name}")]
        return bool(found), found[0] if found else ""
    return False, ""


# --------------------------------------------------------------------------- watch (foreground)

def watch(every: int, iterations: int | None = None, on_report=None, sleep=time.sleep) -> None:
    """Scan every `every` minutes; between scans long-poll Telegram so buttons react instantly."""
    from .notify import runner
    done = 0
    while iterations is None or done < iterations:
        rep = runner.run()
        if on_report:
            on_report(rep)
        done += 1
        if iterations is not None and done >= iterations:
            break
        deadline = time.time() + every * 60
        tg = runner.telegram()
        while time.time() < deadline:
            if tg:
                from .notify.telegram import handle_updates
                key = f"{config.cfg.profile_name}:tg_offset"
                offset = runner._state.get(key) or 0
                ups = tg.poll(offset, wait=min(50, max(1, int(deadline - time.time()))))
                if ups:
                    runner._state.set(key, max(offset, handle_updates(
                        tg, ups, lambda cmd, arg: runner.answer_command(tg, cmd, arg))))
                    runner._state.flush()
            else:
                sleep(min(30, max(1, deadline - time.time())))


# --------------------------------------------------------------------------- GitHub Actions template

def actions_workflow(every: int = 60, lang: str = "en", tz: str = "UTC") -> str:
    minute = 17
    cron = f"{minute} * * * *" if every <= 60 else f"{minute} */{max(1, every // 60)} * * *"
    return f"""# sift — Steam deal alerts from the cloud (runs even when your PC is off).
# Setup: Settings → Secrets and variables → Actions → add the secrets listed below, then enable Actions.
name: sift notifications

on:
  schedule:
    - cron: "{cron}"
  workflow_dispatch:

concurrency: sift

jobs:
  notify:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    env:
      SIFT_HOME: ${{{{ github.workspace }}}}/.sift
      TZ: {tz}
      SIFT_LANG: {lang}
      STEAM_ID64: ${{{{ secrets.STEAM_ID64 }}}}
      STEAM_API_KEY: ${{{{ secrets.STEAM_API_KEY }}}}
      STEAM_COUNTRY: ${{{{ secrets.STEAM_COUNTRY }}}}
      ITAD_API_KEY: ${{{{ secrets.ITAD_API_KEY }}}}
      SIFT_FAMILY: ${{{{ secrets.SIFT_FAMILY }}}}
      SIFT_TELEGRAM_TOKEN: ${{{{ secrets.SIFT_TELEGRAM_TOKEN }}}}
      SIFT_TELEGRAM_CHAT: ${{{{ secrets.SIFT_TELEGRAM_CHAT }}}}
      SIFT_DISCORD_WEBHOOK: ${{{{ secrets.SIFT_DISCORD_WEBHOOK }}}}
      SIFT_NTFY_TOPIC: ${{{{ secrets.SIFT_NTFY_TOPIC }}}}
      SIFT_NOTIFY_MODE: ${{{{ vars.SIFT_NOTIFY_MODE || 'digest' }}}}
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Restore sift state (dedupe, digest queue, hidden games)
        uses: actions/cache/restore@v4
        with:
          path: .sift
          key: sift-${{{{ github.run_id }}}}
          restore-keys: sift-
      - run: pip install --quiet steamsift
      - run: sift notify run
      - name: Save sift state
        if: always()
        uses: actions/cache/save@v4
        with:
          path: .sift
          key: sift-${{{{ github.run_id }}}}
"""
