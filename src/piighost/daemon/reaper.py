"""Reap orphaned ``piighost serve`` processes.

A process is an orphan when its parent process is either:
  - not running anymore (parent is None / NoSuchProcess), or
  - not Claude Desktop (``claude`` / ``Claude.exe``) and not a known
    developer shell or terminal.

The reaper is conservative: it deliberately does NOT kill manual
``piighost serve`` invocations from a developer's terminal (parent is
a shell such as bash, pwsh, cmd.exe, etc.). Those are out of scope;
touching them would be hostile.
"""
from __future__ import annotations

from typing import Iterable

import psutil


# Processes that are allowed to be the parent of a ``piighost serve`` shim.
# Any other live parent causes the shim to be treated as an orphan and reaped.
_SAFE_PARENT_NAMES = {
    # Claude Desktop — the intended host
    "claude",
    "claude.exe",
    # Developer shells / terminals — manual debug runs are explicitly safe
    "bash",
    "sh",
    "zsh",
    "fish",
    "pwsh",
    "pwsh.exe",
    "powershell",
    "powershell.exe",
    "cmd",
    "cmd.exe",
    "windowsterminal.exe",
    "wt.exe",
    "iterm2",
    "terminal",
    "alacritty",
    "kitty",
    "gnome-terminal",
    "konsole",
    "xterm",
}


def _iter_serves() -> Iterable[psutil.Process]:
    """Yield every running ``piighost serve --transport stdio`` process."""
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.cmdline() or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        cmd = " ".join(cmdline).lower()
        if "piighost" in cmd and "serve" in cmd and "stdio" in cmd:
            yield proc


def _is_orphan(proc: psutil.Process) -> bool:
    try:
        parent = proc.parent()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return True
    if parent is None:
        return True
    try:
        parent_name = parent.name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return True
    return parent_name not in _SAFE_PARENT_NAMES


def reap() -> list[int]:
    """Terminate every orphaned shim. Returns list of killed PIDs."""
    killed: list[int] = []
    for proc in _iter_serves():
        if not _is_orphan(proc):
            continue
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                proc.kill()
            killed.append(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return killed
