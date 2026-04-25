"""Reaper kill rules with mocked psutil — no real processes touched."""
from __future__ import annotations

from unittest.mock import MagicMock

from piighost.daemon import reaper


def _proc(pid: int, *, name: str = "python.exe", cmdline: list[str] | None = None,
          parent_name: str | None = "Claude.exe", running: bool = True) -> MagicMock:
    """Build a MagicMock that quacks like a psutil.Process."""
    p = MagicMock()
    p.pid = pid
    p.name.return_value = name
    p.cmdline.return_value = cmdline or [
        "python.exe", "-m", "piighost", "serve", "--transport", "stdio",
    ]
    p.is_running.return_value = running
    if parent_name is None:
        p.parent.return_value = None
    else:
        parent = MagicMock()
        parent.name.return_value = parent_name
        p.parent.return_value = parent
    return p


def test_orphan_with_no_parent_is_killed(monkeypatch) -> None:
    orphan = _proc(7708, parent_name=None)
    monkeypatch.setattr(reaper, "_iter_serves", lambda: [orphan])
    killed = reaper.reap()
    assert killed == [7708]
    orphan.terminate.assert_called_once()


def test_orphan_with_non_claude_parent_is_killed(monkeypatch) -> None:
    orphan = _proc(15732, parent_name="explorer.exe")
    monkeypatch.setattr(reaper, "_iter_serves", lambda: [orphan])
    killed = reaper.reap()
    assert killed == [15732]


def test_shim_with_claude_parent_is_NOT_killed(monkeypatch) -> None:
    shim = _proc(1234, parent_name="Claude.exe")
    monkeypatch.setattr(reaper, "_iter_serves", lambda: [shim])
    killed = reaper.reap()
    assert killed == []
    shim.terminate.assert_not_called()


def test_shim_with_lowercase_claude_parent_is_NOT_killed(monkeypatch) -> None:
    shim = _proc(1234, parent_name="claude")
    monkeypatch.setattr(reaper, "_iter_serves", lambda: [shim])
    assert reaper.reap() == []


def test_manual_run_from_terminal_is_NOT_killed(monkeypatch) -> None:
    """`piighost serve` run from a bash/pwsh terminal must not be reaped."""
    for shell in ("bash", "pwsh", "cmd.exe", "powershell.exe", "WindowsTerminal.exe"):
        manual = _proc(1234, parent_name=shell)
        monkeypatch.setattr(reaper, "_iter_serves", lambda m=manual: [m])
        assert reaper.reap() == [], f"shell {shell} treated as orphan parent"


def test_terminate_then_kill_if_still_running(monkeypatch) -> None:
    orphan = _proc(7708, parent_name=None)
    # Simulate proc surviving terminate
    orphan.is_running.side_effect = [True, True, True]  # always running
    import psutil
    orphan.wait.side_effect = psutil.TimeoutExpired(5)
    monkeypatch.setattr(reaper, "_iter_serves", lambda: [orphan])
    reaper.reap()
    orphan.terminate.assert_called_once()
    orphan.kill.assert_called_once()


def test_does_not_kill_non_serve_python(monkeypatch) -> None:
    monkeypatch.setattr(reaper, "_iter_serves", lambda: [])  # filtered out before
    assert reaper.reap() == []
