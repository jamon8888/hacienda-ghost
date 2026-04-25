# src/piighost/install/service/darwin.py
"""macOS LaunchDaemon install/uninstall for piighost proxy (port 443).

Runs as root so it can bind port 443 on loopback. The vault directory is
passed explicitly so the daemon can locate the vault without relying on HOME.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from piighost.install.service import ServiceSpec

_PLIST_PATH = Path("/Library/LaunchDaemons/com.piighost.proxy.plist")
_LABEL = "com.piighost.proxy"


def _plist_content(spec: ServiceSpec) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{spec.bin_path}</string>
        <string>proxy</string>
        <string>run</string>
        <string>--port</string>
        <string>{spec.port}</string>
        <string>--vault</string>
        <string>{spec.vault_dir}</string>
        <string>--cert</string>
        <string>{spec.cert_path}</string>
        <string>--key</string>
        <string>{spec.key_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <!-- ThrottleInterval prevents launchd from re-spawning more than once
         every N seconds, which avoids hammering the system if the proxy
         crashes immediately on startup. -->
    <key>ThrottleInterval</key>
    <integer>2</integer>
    <!-- ExitTimeOut bounds how long launchd waits for graceful shutdown
         before SIGKILL, keeping restart latency predictable. -->
    <key>ExitTimeOut</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>{spec.vault_dir}/proxy/proxy.log</string>
    <key>StandardErrorPath</key>
    <string>{spec.vault_dir}/proxy/proxy.err</string>
</dict>
</plist>
"""


def install(spec: ServiceSpec) -> None:
    content = _plist_content(spec)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".plist", delete=False) as fh:
        fh.write(content)
        tmp = fh.name
    subprocess.run(["sudo", "cp", tmp, str(_PLIST_PATH)], check=True)
    subprocess.run(["sudo", "chmod", "644", str(_PLIST_PATH)], check=True)
    subprocess.run(["sudo", "launchctl", "load", "-w", str(_PLIST_PATH)], check=True)


def uninstall(spec: ServiceSpec) -> None:
    if _PLIST_PATH.exists():
        subprocess.run(
            ["sudo", "launchctl", "unload", str(_PLIST_PATH)],
            check=False,
        )
        subprocess.run(["sudo", "rm", "-f", str(_PLIST_PATH)], check=False)


def running(spec: ServiceSpec) -> bool:
    result = subprocess.run(
        ["launchctl", "list", _LABEL],
        capture_output=True,
    )
    return result.returncode == 0
